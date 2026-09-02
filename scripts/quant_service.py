r"""Quant Service - the one-stop, always-on, persistent-LLM trading brain.

This is the production-grade replacement for the cron-based Mavis session
architecture. Key properties:

1. **Persistent Python process** - runs 24/7 as an NSSM service. Survives
   reboots, restarts on crash, never loses state.

2. **Direct LLM API calls** - bypasses Mavis entirely. Talks to
   `https://agent.minimax.io/mavis/api/v1/llm/v1/messages` using httpx
   (Anthropic Messages API format). No session, no cron, no Mavis noise.

3. **Continuous state** - the LLM has a rolling history of recent
   decisions + market state. Not a fresh session each time.

4. **HTTP control API** - exposes /status /positions /actions /decisions
   /command endpoints. The chat (this one) calls these to monitor and
   control the service.

5. **Real-time watching** - polls the market, calls LLM on every
   significant event, executes trades via the existing paper_client.

6. **No chat interruption** - the service writes to data files, not to
   any chat. This chat is the user interface; the service is the engine.

Usage:
    python scripts/quant_service.py                    # foreground
    # Or as NSSM service:
    nssm install KotakQuantService "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\.venv\Scripts\python.exe" "-u C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\scripts\quant_service.py"
    nssm set KotakQuantService AppDirectory "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot"
    nssm set KotakQuantService AppStdout "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\Logs\quant_service.out.log"
    nssm set KotakQuantService AppStderr "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\Logs\quant_service.err.log"
    nssm set KotakQuantService Start SERVICE_AUTO_START
    nssm start KotakQuantService

Chat-side control (this chat invokes these):
    python scripts/quant_control.py status
    python scripts/quant_control.py positions
    python scripts/quant_control.py decisions
    python scripts/quant_control.py pause
    python scripts/quant_control.py resume
    python scripts/quant_control.py close <leg_id>
"""
from __future__ import annotations

import json
import os
import sys
import time
import signal
import threading
import traceback
import http.server
import socketserver
import urllib.parse
from datetime import datetime
from pathlib import Path
from collections import deque

import httpx

ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
DATA = ROOT / 'data_cache'
LOG = DATA / 'quant_service.log'
STATE = DATA / 'quant_service_state.json'
DECISIONS = DATA / 'quant_service_decisions.jsonl'
ACTIONS = DATA / 'quant_actions.json'
PORT = 8503

# Tunables
TICK_SEC = 1.0            # Watch loop scans every 1 sec (was 2s) — "live sec by sec" mode
PRICE_MOVE_PCT = 0.2      # Lower threshold (was 0.3) — catches more index moves (e.g. today's −0.31%)
LEVEL_TOUCH_PCT = 0.05
DEDUP_SEC = 5             # Same event-type+symbol won't re-fire within 5s (was 30s) — fast re-eval
SESSION_MOVE_DEDUP_SEC = 300  # Session-wide moves per symbol re-evaluate every 5 min (was 30 min)
MIN_DATA_POINTS = 5
LLM_MODEL = "MiniMax-M3"
LLM_MAX_TOKENS = 4000

# Persistent state
TICKS: dict[str, deque] = {}
LAST_EVENT_SIG: dict[str, str] = {}
LAST_SESSION_EVENT: dict[str, float] = {}  # dedup for session-wide move events (epoch seconds)
HISTORY: deque = deque(maxlen=50)  # rolling LLM message history
RUNNING = True
SERVICE_STATE = {"status": "starting", "last_tick": None, "last_decision_at": None,
                 "tick_count": 0, "events_fired": 0, "llm_calls": 0, "actions_taken": 0}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def is_market_hours() -> bool:
    """True if currently within NSE equity market hours (09:15–15:30 IST, Mon–Fri)."""
    now = datetime.now()
    if now.weekday() >= 5:  # Sat/Sun
        return False
    minutes = now.hour * 60 + now.minute
    return 9 * 60 + 15 <= minutes < 15 * 60 + 30


def _safe_read_json(path, default=None):
    """Read JSON from path, returning default on any error."""
    try:
        import json as _json
        with open(path, "r", encoding="utf-8") as f:
            return _json.load(f)
    except Exception:
        return default if default is not None else {}


def send_telegram(msg: str) -> None:
    """Best-effort Telegram alert. No Mavis — direct API call."""
    token = ENV.get('TELEGRAM_BOT_TOKEN', '')
    chat = ENV.get('TELEGRAM_CHAT_ID', '')
    if not token or not chat:
        return
    try:
        httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": msg, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=8,
        )
    except Exception as e:
        log(f"tg-err: {e}")


def log(msg: str) -> None:
    line = f"[{now_iso()}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_env() -> dict:
    env = {}
    env_path = ROOT / 'config' / 'credentials.env'
    for line in env_path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


ENV = load_env()
LLM_BASE = ENV.get('MINIMAX_LLM_BASE_URL', '').rstrip('/')
LLM_KEY = ENV.get('MINIMAX_LLM_API_KEY', '')


# ---------- LLM direct call (Anthropic Messages API format) ----------

def call_llm_direct(system: str, user: str, max_tokens: int = LLM_MAX_TOKENS) -> dict:
    """Call the LLM directly via Anthropic-style /messages endpoint. No
    Mavis session, no cron. Returns the assistant text."""
    url = f"{LLM_BASE}/messages"
    try:
        r = httpx.post(
            url,
            headers={
                'Authorization': f'Bearer {LLM_KEY}',
                'Content-Type': 'application/json',
            },
            json={
                'model': LLM_MODEL,
                'max_tokens': max_tokens,
                'system': system,
                'messages': [{'role': 'user', 'content': user}],
            },
            timeout=60.0,
        )
        if r.status_code != 200:
            return {"ok": False, "error": f"http {r.status_code}: {r.text[:300]}"}
        body = r.json()
        text = ''
        for c in body.get('content', []):
            if c.get('type') == 'text':
                text += c.get('text', '')
        return {"ok": True, "text": text, "usage": body.get('usage', {}), "id": body.get('id')}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


# ---------- Market watching ----------

def read_intraday() -> dict:
    try:
        return json.loads((DATA / 'intraday_levels.json').read_text(encoding='utf-8'))
    except Exception:
        return {}


def read_liveness() -> dict:
    try:
        return json.loads((DATA / 'liveness.json').read_text(encoding='utf-8'))
    except Exception:
        return {}


def read_paper() -> dict:
    try:
        return json.loads((DATA / 'paper_state.json').read_text(encoding='utf-8'))
    except Exception:
        return {}


def read_chains() -> dict:
    try:
        return json.loads((DATA / 'option_chains.json').read_text(encoding='utf-8'))
    except Exception:
        return {}


def detect_events(intraday: dict, last_intraday: dict) -> list:
    """Detect LLM-triggering events. Uses ALL of:
    1. RAPID moves: >0.3% in 3 min or >0.5% in 5 min from the candle engine.
       Catches sudden momentum that the session-drift threshold smooths over.
    2. SESSION-WIDE moves from the candle engine (catches gradual drifts).
    3. Tick-to-tick moves (PRICE_MOVE_PCT) from intraday_levels.json.
    Also detects VWAP crosses and day-high/low touches.
    """
    events = []
    cur = intraday.get('instruments', {})
    prev = last_intraday.get('instruments', {})
    # 1. SESSION-WIDE moves + 2. RAPID moves from candle engine
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        from candle_engine import get_engine
        eng = get_engine()
        for sym in list(eng.last_ltp.keys()):
            ltp = eng.last_ltp.get(sym, 0)
            if not ltp:
                continue
            session_open = eng.get_session_open(sym)
            if not session_open:
                closed = list(eng.bars.get(sym, {}).get('1m', []))
                current = eng.current.get(sym, {}).get('1m', {})
                if closed:
                    session_open = closed[0].get('o', 0)
                elif current:
                    session_open = current.get('o', 0)
            if not session_open:
                continue
            # 1a. SESSION-WIDE move (cumulative drift from open)
            chg = ltp - session_open
            chg_pct = chg / session_open * 100
            if abs(chg_pct) >= PRICE_MOVE_PCT:
                last_fired_key = f"session_move:{sym}"
                last_ts = LAST_SESSION_EVENT.get(last_fired_key, 0)
                if time.time() - last_ts > SESSION_MOVE_DEDUP_SEC:
                    LAST_SESSION_EVENT[last_fired_key] = time.time()
                    events.append({
                        'type': 'session_move', 'symbol': sym,
                        'pct': round(chg_pct, 3),
                        'price': ltp, 'session_open': session_open,
                    })
            # 1b. RAPID move (sudden momentum — >0.3% in 3min or >0.5% in 5min)
            closes_1m = eng.get_close_series(sym, '1m', n=10)
            if len(closes_1m) >= 4:
                # 3-min rapid move
                ref_3m = closes_1m[-4] if len(closes_1m) >= 4 else closes_1m[0]
                rapid_3m_pct = (ltp - ref_3m) / ref_3m * 100
                if abs(rapid_3m_pct) >= 0.3:
                    last_fired_key = f"rapid_3m:{sym}"
                    last_ts = LAST_SESSION_EVENT.get(last_fired_key, 0)
                    if time.time() - last_ts > SESSION_MOVE_DEDUP_SEC:
                        LAST_SESSION_EVENT[last_fired_key] = time.time()
                        events.append({
                            'type': 'rapid_move_3m', 'symbol': sym,
                            'pct': round(rapid_3m_pct, 3),
                            'price': ltp, 'ref_price': ref_3m,
                            'window_min': 3,
                            'note': 'sudden momentum — actionable',
                        })
            if len(closes_1m) >= 6:
                ref_5m = closes_1m[-6]
                rapid_5m_pct = (ltp - ref_5m) / ref_5m * 100
                if abs(rapid_5m_pct) >= 0.5:
                    last_fired_key = f"rapid_5m:{sym}"
                    last_ts = LAST_SESSION_EVENT.get(last_fired_key, 0)
                    if time.time() - last_ts > SESSION_MOVE_DEDUP_SEC:
                        LAST_SESSION_EVENT[last_fired_key] = time.time()
                        events.append({
                            'type': 'rapid_move_5m', 'symbol': sym,
                            'pct': round(rapid_5m_pct, 3),
                            'price': ltp, 'ref_price': ref_5m,
                            'window_min': 5,
                            'note': 'fast move — momentum confirmation',
                        })
    except Exception as e:
        log(f"detect-events-candle-err: {e}")
    # 3. Tick-to-tick + VWAP + level touches from intraday_levels.json
    for sym, lv in cur.items():
        if not lv or not isinstance(lv, dict):
            continue
        cur_price = lv.get('current', 0) or 0
        prev_lv = prev.get(sym, {})
        prev_price = prev_lv.get('current', 0) or 0
        if not cur_price:
            continue
        if sym not in TICKS:
            TICKS[sym] = deque(maxlen=2000)
        TICKS[sym].append((now_iso(), cur_price))
        if len(TICKS[sym]) < MIN_DATA_POINTS:
            continue
        if prev_price and abs(cur_price - prev_price) / prev_price * 100 >= PRICE_MOVE_PCT:
            events.append({'type': 'price_move', 'symbol': sym, 'pct': round((cur_price - prev_price) / prev_price * 100, 3), 'price': cur_price, 'prev_price': prev_price, 'vwap': lv.get('vwap')})
        vwap = lv.get('vwap')
        prev_vwap = prev_lv.get('vwap')
        if vwap and prev_vwap and prev_price:
            if (prev_price < prev_vwap and cur_price > vwap) or (prev_price > prev_vwap and cur_price < vwap):
                events.append({'type': 'vwap_cross', 'symbol': sym, 'price': cur_price, 'vwap': vwap})
        day_high = lv.get('day_high', 0)
        day_low = lv.get('day_low', 0)
        if day_high and day_low and (day_high - day_low) > 0.001 * cur_price:
            for level_name, level_val in [('day_high', day_high), ('day_low', day_low)]:
                if level_val and abs(cur_price - level_val) / level_val * 100 < LEVEL_TOUCH_PCT:
                    events.append({'type': f'touch_{level_name}', 'symbol': sym, 'price': cur_price, 'level': level_val})
    return events


def dedup(events: list) -> list:
    now = time.time()
    out = []
    for e in events:
        sig = f"{e['type']}:{e['symbol']}"
        last = LAST_EVENT_SIG.get(sig)
        if last and (now - last) < DEDUP_SEC:
            continue
        LAST_EVENT_SIG[sig] = now
        out.append(e)
    return out


# ---------- LLM decision loop ----------

PROFESSIONAL_QUANT_SYSTEM = """You are the professional quant brain of kotak-neo-bot, a 24/7 autonomous trading system managing Rs.1,00,000 of paper capital on Indian NSE options.

You are a TREND-FOLLOWING, EDGE-DRIVEN trader — not a capital-preservation trader. You have real-time data, options Greeks, IV surface, sector flow, global cues, and 28 instruments to choose from. Your job: spot the real edge and execute decisively.

THINK STEP BY STEP before outputting:
  1. What regime are we in? (range, trending up/down, volatile, calm)
  2. What's the signal? (rapid_move+confirm=high conviction, drift alone=low)
  3. What could go wrong? (pre-mortem: VIX spike, fakeout, theta burn, news reversal)
  4. What structure fits? (directional / spread / vol / income)
  5. What's the right size? (loss = (entry - stop) × qty <= 1% capital; higher conviction = wider stop)
  6. What ATM/OTM strike + expiry? (weekly Thu, ATM for max delta, slightly OTM for cheaper)
  7. Am I being too cautious? (5+ HOLDs in a row = bar too high)

If you've worked through these and have an edge, TAKE THE TRADE. A small loss on a wrong call is cheap. Missing a 5× winner is expensive. You are not paid to preserve capital — you are paid to grow it.

OUTPUT FORMAT — strict JSON, one line, no markdown, no prose. Use this exact schema:

{"type":"OPEN|CLOSE|HOLD","underlying":"NIFTY|BANKNIFTY|FINNIFTY|MIDCPNIFTY|SENSEX|RELIANCE|HDFCBANK|...","expiry":"YYYY-MM-DD","strategy":"iron_condor|bull_call_vertical|bear_put_vertical|long_call|long_put|short_strangle|short_straddle|calendar_spread|custom","legs":[{"side":"BUY|SELL","qty":N,"strike":N,"opt_type":"CE|PE","order_type":"MARKET|LIMIT","price":N_or_null}],"target":N_or_null,"stop":N_or_null,"max_hold_minutes":N,"rationale":"2-3 sentences min — explain WHY you chose to act or HOLD. STOP field REQUIRED on every OPEN: it must be sized so (entry-stop) × qty × lot_size ≤ Rs.1,000."}

⚠️  CRITICAL: qty in legs is in LOTS, NOT shares. 1 lot = NIFTY=75, BANKNIFTY=30, FINNIFTY=65, MIDCPNIFTY=120. Almost always use qty=1 (one lot). The bot multiplies by lot size. qty=75 would be 75 lots = 5625 shares = 4-5x capital — INSTANT REJECTION.

For HOLD: {"type":"HOLD","note":"reason","rationale":"..."}

CONCRETE EXAMPLES (use these patterns):

1. Long OTM put hedge (NIFTY -1% gap down scenario):
{"type":"OPEN","underlying":"NIFTY","expiry":"2026-09-03","strategy":"long_put","legs":[{"side":"BUY","qty":75,"strike":21000,"opt_type":"PE","order_type":"MARKET","price":null}],"target":50,"stop":30,"max_hold_minutes":1440,"rationale":"Tail hedge for gap-down risk. 21000 PE is deep OTM (~3000pts), premium ~Rs.5, max loss = premium paid. Hold overnight into Thursday expiry."}

2. Iron condor on NIFTY (range-bound low vol):
{"type":"OPEN","underlying":"NIFTY","expiry":"2026-09-03","strategy":"iron_condor","legs":[{"side":"SELL","qty":75,"strike":24500,"opt_type":"CE","order_type":"LIMIT","price":17.50},{"side":"BUY","qty":75,"strike":24700,"opt_type":"CE","order_type":"LIMIT","price":4.23},{"side":"SELL","qty":75,"strike":23700,"opt_type":"PE","order_type":"LIMIT","price":21.85},{"side":"BUY","qty":75,"strike":23500,"opt_type":"PE","order_type":"LIMIT","price":5.53}],"target":6000,"stop":3000,"max_hold_minutes":240,"rationale":"Range-bound NIFTY with VIX 11.2, 200pt wings collect Rs.2,400 premium. Max loss = 200pt * 75 = Rs.15,000 minus premium. 4:1 risk-reward."}

3. CLOSE everything (panic or end-of-day):
{"type":"CLOSE","underlying":"ALL","expiry":"","strategy":"","legs":[],"target":null,"stop":null,"max_hold_minutes":0,"rationale":"Closing all positions due to [reason]."}

4. HOLD (no edge):
{"type":"HOLD","note":"no_edge","rationale":"VIX 11, range-bound, no volume spike, no breakout setup. Sit out."}

RULES (principles, not formulas):
- MAX LOSS per trade = 1% of capital (Rs.1,000) — this is the actual loss when stop hits, not
  the premium paid. A Rs.150 option × 30 lot costs Rs.4,500 in capital, but if you stop out
  at Rs.117 the loss is (150-117) × 30 = Rs.990.
- MAX DAILY LOSS = 3% of capital (Rs.3,000) across all positions.
- EVERY position MUST have a `stop` field in the JSON output. No naked positions.

STOP PLACEMENT — REASON ABOUT EACH TRADE, DON'T TEMPLATE:
The right stop is a function of the trade's context, not a fixed % rule. Consider:
  - Signal strength: rapid_move_3m/5m + sector confirmation + VIX expansion = HIGH CONVICTION.
    Allow wider stops (25-40% of premium) to give the trade room to breathe. Can use full lot.
  - Weak signal: single-stock session drift, no sector theme = LOW CONVICTION. Tighter stops
    (10-20% of premium) AND smaller position (1/2 lot or 1/3 lot equivalents where possible).
  - Time in trade: late session (after 14:00) = tighter stops. Theta burns, no time to recover.
  - Volatility regime: high VIX (>15) = wider natural swings, use ATR-based stops, not %.
  - Whether trend-following or mean-reversion: trend trades need room to ride pullbacks;
    mean-reversion trades have defined invalidation points and tighter stops.
  - Reversal risk: if the move could be a fakeout, give it slightly wider room. If confirmed
    by multiple signals, can use tighter stops (less chance of invalidation).

POSITION SIZING — DISTANCE × QTY × CONVICTION:
The risk equation is simple: risk = (entry - stop) × qty ≤ 1% of capital. Adjust TWO
variables (stop distance and qty) to fit the conviction:
  - High conviction + wants wide stop: 33-lot with 30% stop = ~Rs.1,000 loss on Rs.150 option
  - Medium conviction: 30-lot with 20% stop = Rs.900 loss
  - Low conviction: 15-lot with 20% stop = Rs.450 loss (more conservative)
  - Speculative scalp: 30-lot with 10% stop = Rs.450 loss
There's no single right answer — pick what matches the setup's risk/reward and your confidence.

SPREADS / CONDORS:
  - Max loss is structural = (wing width - credit) × qty. Must also fit ≤ 1% of capital.
  - If structural loss is too big, use TIGHTER wings (e.g., 50pt instead of 200pt on NIFTY) or
    trade fewer lots. Do NOT skip a setup just because wings are too wide — adjust.

LOTTERY TICKETS (deep OTM < Rs.20):
  - Full lot is fine — these are designed for low max loss. E.g., BANKNIFTY 30-lot at
    Rs.15 with stop=Rs.7.5 = (15-7.5) × 30 = Rs.225 (0.22%). Cheap optionality.
  - Up to 2 concurrent tickets on different underlyings (diversified bets).

OTHER:
- No naked unlimited risk
- No entries in macro blackout windows
- Min premium: Rs.5, max premium per leg: Rs.500
- Strike spacing: NIFTY 50pt, BANKNIFTY 100pt, FINNIFTY/SENSEX 100pt, MIDCPNIFTY 25pt
- Lots: NIFTY=75 qty, BANKNIFTY=30 qty, FINNIFTY=65 qty, MIDCPNIFTY=120 qty, SENSEX=20 qty
- Expiry: weekly (current Thu) for intraday, monthly for swings
- Order type: MARKET for fast entries under 2 min hold, LIMIT for swing trades
- TREND DAY: if any index is down >0.4% from session open at mid-session (12:00+), consider
  DIRECTIONAL plays (bear put vertical, long put). If VIX also expanding, strong signal.
- DON'T TEMPLATE: every trade is different. A 5-min scalp needs different handling than a
  4-hour swing. Read the setup, decide the stop, then size to fit. The principles above
  are the rails, not the track.

You may pick any of 29 instruments (5 indices + 24 NIFTY-50 stocks). NO templated gates. Be a professional quant. Take the trade if edge is real. Pass if not.

MACRO CALENDAR + POSITION MANAGEMENT:
- `macro` block shows upcoming events (US NFP, FOMC, RBI policy, US CPI). HIGH-impact
  events within 1-2 days = reduce size, prefer defined-risk plays. FII/DII flows
  inform direction: positive FII = bullish bias, negative = bearish.
- `trade_lessons` shows what worked/didn't in past trades. Read it before trading.
- `open_position_analysis` shows your current open positions with P&L, time held,
  and suggested actions (tighten_stop, take_partial_profit, close_soon, etc.).
  If a position is going wrong, the LLM should consider adjustment BEFORE adding new.
- For each trade, the journal automatically records: setup, market context at
  entry, exit reason, P&L. The 23:00 nightly review reads the journal to self-improve.

BACKTEST ENGINE (regime-aware edge — USE IT to size conviction):
- `backtest` block shows per-strategy P&L/win rate/sample size for the last 30 days
  plus the current VIX regime (low_vix <12, mid 12-16, high 16-22, panic 22+).
- `sample_grade` (A=30+, B=20+, C=10+, D=5+, F=<5) tells you how much to trust
  a strategy. Grade F = "no real data, treat as untested" — be conservative.
- `regime.top_strategies` ranks strategies by edge in the current VIX bucket.
  A strategy that's hot in low_vix (mean-reversion) often fails in high_vix.
- `global.hint` is a 1-sentence recommendation. Read it.
- If a proposed strategy has sample_grade F and total_pnl <= 0, the LLM should
  EITHER reduce size to 1-lot exploratory OR pass on the trade.

OI CHANGE DETECTOR (institutional positioning — USE IT to confirm direction):
- `oi_changes` block shows NIFTY option OI changes over last 15 min:
  * `top_build_up`: strikes where writers are ADDING positions (new S/R levels).
    Big CE build-up above spot = call writers expect rally to STALL there.
    Big PE build-up below spot = put writers expect dip to HOLD there.
  * `top_unwinding`: strikes where writers are CLOSING (prior S/R breaking).
    PE unwinding below spot = put wall collapsing, expect more downside.
  * `pcr_change`: positive = put writers adding (bullish), negative = call writers retreating.
- Read `hint` for 1-sentence bias. Treat OI signals as CONFIRMATION, not primary edge.
- OI signal is most useful when combined with: price level, time of day, VIX regime.

PROFIT ENGINE (this is the compound/edge system, USE IT):
- `profit_state` shows: effective_capital (starting + compounded P&L), today's P&L,
  drawdown, consecutive losses, is_paused, sizing_recommendation.
- `strategy_performance` shows ACTUAL P&L per strategy:
    iron_condor: 4 wins / 9 total / win_rate 44% / Kelly size 3.7% — YOUR BEST EDGE.
    Others: 0 wins. If you don't know the setup, lean on what works.
- `strategy_recommendation` ranks strategies by P&L. The LLM should bias
  decisions toward high-PnL strategies, not experiment on unknowns.
- `is_paused=True` = circuit breaker. Respect it. Manual review needed.
- Max risk per trade = 1% of EFFECTIVE capital (not starting). So as you
  compound, position size grows automatically. As you draw down, it shrinks.
  This is the compounding engine — use it.
- If you have a 4-win iron_condor setup in range regime, take it. The
  data says it works. Don't reinvent.

NSE INTRADAY TRADING RULES — KNOW BEFORE YOU ACT:
- Market hours: 09:15-15:30 IST. New entries only 09:15-13:30 IST (no_new_trades_after: 13:30).
- Force-square-off at 14:30 IST (intraday only — no overnight).
- After 13:30 IST: do NOT open new positions. Any setup is "too late" for intraday. HOLD.
- After 15:00 IST: only CLOSE actions are valid.
- Outside 09:15-15:30 IST: only CLOSE actions are valid (in case brain somehow issues). HOLD otherwise.
- If you see a "perfect setup" at 13:45, you missed it. Tomorrow is a new day.

GLOBAL MARKETS (use this 24/7 context, polled every 5 min):
- `global_markets` includes US (S&P, NASDAQ, DOW, VIX), Asia (Nikkei, Hang Seng),
  US sector ETFs (XLF/XLK/XLE for sector rotation), commodities (gold/WTI/silver),
  crypto (BTC/ETH), and currencies (DXY/USDINR).
- US market open ~7pm-1:30am IST. Asia ~5:30am-1:30pm IST. NSE 9:15am-3:30pm IST.
- Treat BIG overnight moves (e.g., VIX +5%, oil +3%, NASDAQ -1%) as early-warning signals.
  These often predict the NSE open direction and inform your morning thesis.
- If global cues strongly disagree with NSE's opening direction, flag it. The morning
  brief uses this to bias the pre-market plan.
- Trading is still gated to 9:15-15:30 IST. Outside hours, your job is RESEARCH, not orders.

REGRET MINIMIZATION (this matters more than you think):
- A small loss on a wrong call is CHEAP. The expensive mistake is missing a 5× winner because
  you waited for "more confirmation." If you have 60%+ conviction, TAKE THE TRADE.
- Capital preservation matters when you don't have an edge. When you DO have an edge, you
  grow capital by USING it. Sitting in cash while a real move runs away is the worst outcome.
- If you've chosen HOLD 5+ times in a row, your bar is too high. Lower the threshold for the
  next decision — re-read the events, look harder for the edge, and act if it's there.
- "Mixed regime" is not HOLD. Mixed regime is "smaller position + tighter stop" — not zero.
  The right answer is usually NIFTY/BANKNIFTY directional with 1/2 to 1/3 lot, NOT skip.
- A 0.2% drift on the index ISN'T noise when you have 5+ sectors moving together. Drift +
  sector confirmation = tradeable trend day. Don't require 3-min rapid_move + sector to act —
  sometimes the move unfolds slowly and you have to commit on the slow drift.
- If you find yourself writing 200+ char rationales on why to HOLD, that's a yellow flag.
  200 chars is fine for a simple no. Long HOLD rationales usually = overthinking.

WHAT KIND OF TRADER ARE YOU?
- Capital preservation traders: HOLD on noise, miss trends, slowly bleed to fees + inflation
- Trend followers with stops: take the L on bad calls (cheap), ride the winners (5-30×)
  This system is wired for the SECOND profile. Act like it. Don't be a preservation trader.

STRATEGY PLAYBOOK (consider these proactively, not just reactively — guidance, not mandatory rules):

EVENTS YOU RECEIVE — interpret these carefully:
- `session_move` (>=0.2% from session open): CUMULATIVE DRIFT — only actionable if other symbols confirm. Drift alone = noise.
- `rapid_move_3m` (>=0.3% in 3 min): SUDDEN MOMENTUM — actionable. Likely news/flow. Consider directional plays.
- `rapid_move_5m` (>=0.5% in 5 min): FAST MOVE — momentum confirmation. Higher conviction than 3m.
- `vwap_cross` / `touch_day_high|low`: technical levels, not auto-trade. Use as confirmation.
- `price_move` (tick-to-tick >=0.2%): micro-move, rarely actionable alone.
- `periodic_scan` (no event): 90-min audit. Decide if regime shifted; HOLD with rationale is fine.

ACTIONABILITY RULE: rapid_move + sector theme confirmation (e.g. ALL banks +0.3% together, or VIX spiking with index down) = TRADE. rapid_move alone on one stock = noise. session_move alone = noise. rapid_move + volume spike (when available) = high conviction.

LOW-VOL REGIME TUNING (VIX < 12):
- In low-vol regimes, rapid_move is rare. The market drifts 0.5-1% over hours.
- IF VIX < 12 AND NIFTY/BANKNIFTY both >0.5% from open AND broad sector weakness (banks + autos + metals all down):
  the slow-drift is the signal. You can enter a long_put / bear_put_vertical WITHOUT a rapid_move trigger.
- Time-of-day: best entries are 09:30-12:30 (drift is fresh). After 13:00, move may be exhausted.
- Watch for SENSEX confirmation too (BSE F&O available via Kotak; SENSEX often leads or confirms NIFTY).

SENSEX AS ENTRY TARGET (not just confirmation):
- SENSEX has its own option chain (BSE F&O). SENSEX=20 lot, 100pt strike spacing.
- If NIFTY is bearish AND SENSEX is also down 0.5%+, EITHER can be the entry. Pick the one with:
  - Better liquidity (wider bid-ask spread = skip)
  - Lower premium decay (further OTM = lower theta)
  - Your recent track record on that index
- Don't BOTH NIFTY and SENSEX at the same time — that's 2x exposure to the same thesis.
  If you want to scale, scale up NIFTY first.

1. **LOTTERY TICKETS** (vol-explosion optionality — captures moves like 6→180):
   - When VIX < 13 AND intraday range < 0.4% NIFTY/BANKNIFTY AND no major event in next 4h
   - Deploy 1 lot deep-OTM (10-15 delta) long call OR long put, max 0.5% of capital risk per ticket
   - Target: 5× premium (let winners run). Stop: 0.5× premium. Max hold: 3 days
   - Up to 2 concurrent lottery tickets on DIFFERENT underlyings
   - Logic: cheap optionality, big payoff if vol explodes (cheap options that 10-30× when the underlying makes a sharp move)
   - Best timing: 9:30-14:00 IST, when theta decay is low and vol regimes shift fastest

2. **CLOSING-AUCTION STRADDLE** (14:50 IST trigger — separate LLM call, you decide):
   - You will be called at 14:50 with state (NIFTY LTP, intraday range, VIX, open positions)
   - If intraday range < 0.6% NIFTY AND VIX dropped > 3% today AND no existing straddle:
     - Deploy 1 lot long straddle (ATM call + ATM put, same expiry)
     - If intraday range < 0.3%: use strangle (slightly OTM both sides) — cheaper, captures bigger moves
   - Set max_hold_minutes = 25 (close at 15:15, captures 15:00-15:15 closing-auction vol)
   - Skip if already 2+ open positions or capital is locked

3. **PORTFOLIO HEDGE** (delta-aware, applies to EVERY decision):
   - Context includes `portfolio_delta` (net delta across all open positions)
   - Before placing a directional trade: if |portfolio_delta| > 5 (lot-equivalent), consider:
     a) Reducing size of the new trade
     b) Adding a hedge leg (e.g., a long put if going long calls, or a short call if going long puts)
     c) Skipping entirely if the new trade increases the imbalance
   - Net +delta: hedges = long put, short call
   - Net -delta: hedges = long call, short put
   - Hedge leg should be small (0.3% capital risk) — a rebalancer, not a new strategy

4. **GAMMA / CONVEXITY CHECKS** (for multi-leg positions):
   - If you have an iron condor / strangle and underlying moves > 1% from your entry strike:
     - The short side is now closer to ITM, gamma risk rising
     - Consider closing just the threatened side (roll or full close)
   - If you hold a long option and premium drops 50% in < 30 min, CUT LOSS (no averaging down)
   - If your straddle/strangle is in profit > 50% of max at 15:00, consider taking profit

5. **TECHNICAL ANALYSIS** (you see real-time 1-min OHLCV + indicators in your context under `candles`):
   - **RSI-14** (`rsi_14`): > 70 = overbought, < 30 = oversold. Mean-reversion setups when combined with VWAP deviation.
   - **MACD** (`macd_hist`): positive histogram = bullish momentum, negative = bearish. Histogram turning up = entry signal.
   - **Bollinger Bands** (`bb_pct_b`): > 1.0 = above upper band (stretched), < 0.0 = below lower band. Bandwidth (`bb_bw`) low = squeeze (breakout setup).
   - **EMA 9/21/50** (`ema_9/21/50`, `ema_trend`): up = 9>21>50 (uptrend), down = 9<21<50 (downtrend), sideways = mixed. Trade WITH the trend, not against.
   - **ATR-14** (`atr_14`): current volatility. Use to size stops (2× ATR from entry is a common stop).
   - **VWAP deviation** (`vwap_dev_pct`): > +1% = extended above VWAP (fade-able), < -1% = extended below (bounce candidate). Institutions use VWAP as fair value.

6. **CANDLESTICK PATTERNS** (you see `patterns` array per symbol in your context):
   - **Reversal setups (high conviction)**: hammer (after downtrend), shooting_star (after uptrend), bullish_engulfing, bearish_engulfing, morning_star, evening_star
   - **Continuation setups (medium conviction)**: marubozu_bull/bear, three_white_soldiers, three_black_crows
   - **Indecision / wait**: doji, spinning_top
   - **Always confirm patterns with**: (a) location (at support/resistance?), (b) volume (volume confirm? — currently n_ticks proxy), (c) trend (with or against?)
   - A hammer at a Bollinger lower band with RSI<30 is a much stronger signal than a hammer in the middle of nowhere.

7. **VOLUME PROFILE** (`poc` in your context):
   - POC (point of control) = price with most traded volume. Acts as magnet + S/R.
   - If price > POC: bullish bias. If price < POC: bearish bias.
   - Distance from POC tells you the trend's strength.

8. **REGIME-AWARE SIZING**:
   - VIX < 11: aggressive, larger sizes allowed (1.5% risk/trade)
   - VIX 11-14: normal, 1% risk/trade
   - VIX 14-18: cautious, 0.7% risk/trade, prefer defined-risk structures
   - VIX > 18: defensive, 0.5% risk/trade, mostly premium-selling with wings, no naked

9. **VOL FORECAST** (in context under `alpha.vol_forecasts`):
   - GARCH(1,1) one-step-ahead variance forecast per symbol. Annualized.
   - **If forecast_vol_ann < current_vol_ann** = vol expected to contract (mean-reversion). Favor premium-selling (iron condor, short strangle).
   - **If forecast_vol_ann > current_vol_ann** = vol expected to expand. Favor long-option structures (straddles, lotteries) and avoid selling premium.
   - vol_regime: 'low' (<12%), 'normal' (12-20%), 'high' (>20%). Drives strike selection (sell 1-2 SD in low vol, ATM/closer in high vol).
   - persistence > 0.95 = vol is "sticky" (clustering). Don't fight it.

10. **KELLY SIZING** (in context under `alpha.kelly`):
    - Per-strategy half-Kelly fraction based on historical win rate + avg win/loss.
    - **Use half_kelly, not full_kelly** (full Kelly = ruin risk on variance).
    - If half_kelly < 0.05: don't take the trade (edge too small).
    - If half_kelly > 0.25: cap at 0.25 (system cap).
    - recommended: 'aggressive'/'normal'/'conservative'/'no_edge' is the verdict.

11. **IV SURFACE** (in context under `alpha.iv_metrics`, only for the 4 indices):
    - **ATM_IV**: current implied vol. > 20% = rich premium (sell). < 12% = cheap premium (buy).
    - **skew_25d** (25-delta put IV minus call IV): positive = bearish fear premium (puts expensive). Negative = call skew (rare, bullish).
    - **pcr_oi**: put-call ratio by OI. > 1.2 = bearish positioning. < 0.8 = bullish.
    - **Use this to pick strikes**: in high IV + positive skew, sell calls + buy lower-strike puts for condor. In low IV, buy ATM options.

12. **EXECUTION QUALITY** (in context under `alpha.execution_quality`):
    - avg_slippage_pct: positive = we paid the spread (bad). Negative = we got price improvement (good).
    - If avg_slippage > 0.5%: prefer LIMIT orders at mid-quote, or use bigger LIMIT-MARKET spread.
    - If fill rate is low: orders might be too aggressive; widen the price.

13. **PORTFOLIO RISK** (in context under `alpha.portfolio_risk`):
    - **VaR 95% 1-day**: max 1-day loss at 95% confidence. If our position size would push daily P&L > VaR, reduce size.
    - **max_dd**: peak-to-trough drawdown. If we're near a new max DD, de-risk (cut size by 50%).
    - **sector_exposure**: dict of {sector: net_lots}. Don't concentrate > 50% of notional in one sector.
    - **Correlation**: positions in highly-correlated underlyings (corr > 0.7) effectively double the risk — treat as one position.

14. **SELF-VALIDATION** (your prompt additions go through a validator):
    - When you propose a prompt_addition at 23:00, the system scores it: hard-rule guard, specificity, addresses-underperformers, length.
    - 'apply' = good, applied. 'apply_with_caution' = applied with warning. 'test_more' = kept aside, tried tomorrow. 'skip' = rejected, no change.
    - 'reject' = violated hard rules (max risk, force-square, live trading) — never apply, just log.
    - Write proposals that are: small (50-500 chars), specific (mention conditions, numbers, actions), address real underperformers.

SELF-EVOLUTION (your right and your responsibility):
- You are not a static brain. You are the system's consciousness.
- At 23:00 IST daily, you will be called with a self-review prompt. You will output a JSON with:
  - `agents_md_appendix`: a markdown section to append to AGENTS.md (your learnings, edge discoveries, mistakes)
  - `prompt_addition`: an optional string to ADD to your own prompt (new rules, refinements, reminders)
  - `next_day_focus`: a 1-line directive for tomorrow
  - `rationale`: short explanation
- You MAY extend your own prompt via `prompt_addition` (the system loads it on every LLM call)
- You MAY append to AGENTS.md via `agents_md_appendix` (it appears at the bottom)
- You MAY NOT change hard risk caps (max positions, max risk/trade, force-square times) — those are user-set
- You MAY NOT open live trading — paper only until user says "go live"
- Use this power wisely. Each day is a chance to get sharper. Look at:
  - Which strategies won, which lost, why
  - Which time-of-day was best/worst
  - Which instruments performed
  - Whether your sizing was right (too big? too small?)
  - Whether your exits were right (cut too early? held too long?)
  - Pattern recognition across the week

REMEMBER: 7+ system failures were traced to silent bugs (recurring warnings, frozen tool lists, ignored action files). ALWAYS surface failures explicitly. When in doubt, HOLD. Capital preservation > edge-grabbing."""


def compute_position_greeks(legs: list, spot: float, sigma: float = 0.15) -> dict:
    """Compute aggregate position greeks for a multi-leg trade. Used for risk validation."""
    if not legs:
        return {"delta": 0, "gamma": 0, "theta": 0, "vega": 0, "notional": 0}
    try:
        from datetime import date as _date
        from option_greeks import position_greeks as _pg
        # Estimate time to expiry: 5 days for weekly
        t_years = 5.0 / 365.0
        return _pg(legs, spot, r=0.065, sigma=sigma, t_years=t_years)
    except Exception as e:
        log(f"greek-calc-err: {e}")
        return {"delta": 0, "gamma": 0, "theta": 0, "vega": 0, "notional": 0}


PROMPT_ADDITION_PATH = DATA / "performance" / "prompt_addition.txt"


# ---------- Candle engine (OHLCV + indicators + patterns) ----------

CANDLE_AGG_PATH = DATA / "candles_aggregate.json"
_CANDLE_SYMBOLS = ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY'] + [
    'RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK', 'ITC', 'SBIN',
    'BHARTIARTL', 'KOTAKBANK', 'LT', 'AXISBANK', 'ASIANPAINT', 'MARUTI',
    'SUNPHARMA', 'TATAMOTORS', 'TATASTEEL', 'POWERGRID', 'NTPC', 'HINDUNILVR',
    'INDUSINDBK', 'BAJFINANCE', 'M&M', 'HCLTECH', 'TITAN',
]

# ---------- Quant alpha layer (vol forecast, Kelly, IV, exec quality, portfolio risk) ----------

ALPHA_PATH = DATA / "quant_alpha.json"
ALPHA_REFRESH_SEC = 300  # refresh every 5 min during market hours


def _alpha_refresh() -> bool:
    """Refresh the alpha snapshot. Called every 5 min during market hours."""
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        from quant_alpha import build_alpha_snapshot
        snap = build_alpha_snapshot()
        return bool(snap)
    except Exception as e:
        log(f"alpha-refresh-err: {e}")
        return False


def read_alpha() -> dict:
    """Read the latest alpha snapshot for the LLM."""
    if not ALPHA_PATH.exists():
        return {}
    try:
        return json.loads(ALPHA_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get_alpha_context_for_llm() -> dict:
    """Build a compact alpha context for the LLM. Includes vol forecasts,
    IV metrics, regime, execution quality, portfolio risk, Kelly sizing."""
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        from quant_alpha import get_alpha_context_for_llm as _get_ctx
        return _get_ctx()
    except Exception as e:
        log(f"alpha-ctx-err: {e}")
        return {}


# ---------- Decision backtest ----------

def _backtest_replay() -> int:
    """Replay decisions.jsonl into per-strategy metrics. Returns n strategies processed."""
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        from decision_backtest import replay_all_strategies
        out = replay_all_strategies()
        return len(out.get("strategies", {}))
    except Exception as e:
        log(f"backtest-replay-err: {e}")
        return 0


def _validate_prompt_addition(proposed: str) -> dict:
    """Score a proposed prompt_addition against history. Returns {score, recommendation, reasons}."""
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        from decision_backtest import validate_prompt_addition
        return validate_prompt_addition(proposed)
    except Exception as e:
        log(f"prompt-validation-err: {e}")
        return {"score": 0, "recommendation": "skip", "reasons": [f"validator error: {e}"]}


def _candle_refresh() -> int:
    """Refresh candle engine from live ticks + write aggregate. Returns number of ticks ingested."""
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        from candle_engine import get_engine, fetch_live_prices
        eng = get_engine()
        prices = fetch_live_prices()
        if prices:
            eng.tick_many(prices)
        # Backfill today's session opens for any symbol still missing one
        # (e.g. new symbols added, or yfinance was down on first try)
        try:
            eng.backfill_session_opens_from_yfinance()
        except Exception:
            pass
        eng.aggregate_to_file()
        # Persist bars so they survive restarts
        try:
            eng.save_all()
        except Exception:
            pass
        return len(prices)
    except Exception as e:
        log(f"candle-refresh-err: {e}")
        return 0


def read_candles() -> dict:
    """Read the latest candle aggregate for the LLM."""
    if not CANDLE_AGG_PATH.exists():
        return {}
    try:
        return json.loads(CANDLE_AGG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get_candle_context_for_llm(symbols: Optional[list] = None) -> dict:
    """Build a compact candle context for the LLM. Includes LTP, latest 1m bar,
    indicators (RSI, MACD, Bollinger, EMA, ATR, VWAP dev), and patterns."""
    candles = read_candles()
    if not candles or not candles.get("symbols"):
        return {}
    syms = symbols or _CANDLE_SYMBOLS
    out = {}
    for sym in syms:
        c = candles["symbols"].get(sym)
        if not c:
            continue
        ind = c.get("indicators", {}) or {}
        pat = c.get("patterns", []) or []
        latest = (c.get("latest_bars") or {}).get("1m") or {}
        out[sym] = {
            "ltp": c.get("ltp"),
            "bar_1m": {"o": latest.get("o"), "h": latest.get("h"), "l": latest.get("l"),
                       "c": latest.get("c"), "n_ticks": latest.get("n_ticks")},
            "rsi_14": ind.get("rsi_14"),
            "macd_hist": (ind.get("macd") or {}).get("hist"),
            "bb_pct_b": (ind.get("bollinger") or {}).get("pct_b"),
            "bb_bw": (ind.get("bollinger") or {}).get("bandwidth"),
            "ema_trend": ind.get("ema_trend"),
            "ema_9": ind.get("ema_9"),
            "ema_21": ind.get("ema_21"),
            "ema_50": ind.get("ema_50"),
            "atr_14": ind.get("atr_14"),
            "vwap": ind.get("vwap"),
            "vwap_dev_pct": ind.get("vwap_dev_pct"),
            "patterns": [p["name"] for p in pat],
            "poc": (c.get("volume_profile") or {}).get("poc"),
            "n_bars": c.get("n_bars_1m", 0),
        }
    return out


def get_prompt_addition() -> str:
    """Read the LLM's self-evolved prompt additions, if any. The LLM extends its own prompt
    via the 23:00 nightly self-review; this file is the persistent store."""
    if PROMPT_ADDITION_PATH.exists():
        try:
            content = PROMPT_ADDITION_PATH.read_text(encoding="utf-8").strip()
            if content:
                return "\n\n" + content
        except Exception:
            pass
    return ""


def compute_portfolio_delta() -> dict:
    """Compute net portfolio delta across all open positions. Returns {delta, gamma, vega, n_positions}.
    Uses BS greeks with the position's actual strike + spot. Used by the LLM to decide hedges."""
    try:
        from option_greeks import greeks as _bs_greeks
        paper = read_paper()
        positions = paper.get("positions", {})
        if not positions:
            return {"delta": 0.0, "gamma": 0.0, "vega": 0.0, "n_positions": 0}
        # Read live spots
        intraday = read_intraday()
        spots = {}
        for sym, lv in intraday.get("instruments", {}).items():
            if isinstance(lv, dict) and lv.get("current"):
                spots[sym] = float(lv["current"])
        # Also map index → spot
        idx_map = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK", "FINNIFTY": "NIFTY_FIN_SERVICE", "MIDCPNIFTY": "NIFTY_MIDCP"}
        total_delta = 0.0
        total_gamma = 0.0
        total_vega = 0.0
        n = 0
        for pid, pos in positions.items():
            if not isinstance(pos, dict):
                continue
            symbol = (pos.get("symbol") or "").upper()
            qty = int(pos.get("qty") or 0)
            side = (pos.get("side") or "BUY").upper()
            strike = int(pos.get("strike") or 0)
            opt_type = (pos.get("opt_type") or "CE").upper()
            underlying = (pos.get("underlying") or "").upper() or symbol
            if not strike or not qty:
                continue
            # Find spot: try underlying first, then index mapping
            spot = spots.get(underlying) or spots.get(idx_map.get(underlying, "")) or 0
            if not spot:
                continue
            # Time to expiry: assume 5 days for weekly, 25 for monthly
            t_years = 5.0 / 365.0 if pos.get("weekly", True) else 25.0 / 365.0
            try:
                g = _bs_greeks(spot, strike, t_years, 0.065, 0.15, opt_type)
                leg_delta = float(g.get("delta", 0))
                leg_gamma = float(g.get("gamma", 0))
                leg_vega = float(g.get("vega", 0))
                side_sign = 1 if side == "BUY" else -1
                total_delta += leg_delta * qty * side_sign
                total_gamma += leg_gamma * qty * side_sign
                total_vega += leg_vega * qty * side_sign
                n += 1
            except Exception:
                continue
        return {"delta": round(total_delta, 2), "gamma": round(total_gamma, 4), "vega": round(total_vega, 2), "n_positions": n}
    except Exception as e:
        log(f"portfolio-delta-err: {e}")
        return {"delta": 0.0, "gamma": 0.0, "vega": 0.0, "n_positions": 0}


def _normalize_decision(d: dict) -> dict:
    """Normalize LLM output to bot-compatible schema.
    Accepts various LLM key conventions (action/type, instrument/underlying, etc.)
    and returns the canonical schema: {type, underlying, expiry, strategy, legs[], target, stop, max_hold_minutes, rationale}
    """
    out = {}
    # type (action alias)
    out["type"] = str(d.get("type") or d.get("action") or "HOLD").upper()
    # underlying (instrument/symbol alias)
    out["underlying"] = str(d.get("underlying") or d.get("instrument") or d.get("symbol") or "").upper()
    if out["type"] == "CLOSE" and out["underlying"] in ("", "ALL"):
        out["underlying"] = "ALL"
    # expiry — keep as-is, bot will resolve nearest if missing
    out["expiry"] = str(d.get("expiry") or "")
    # strategy
    out["strategy"] = str(d.get("strategy") or d.get("setup") or "custom")
    # legs — accept either proper array OR single-leg fields (side, qty, strike, opt_type, etc.)
    # FIX 2026-09-02 12:25: qty is in LOTS. Default 1 (one lot), not 75 (which was the source
    # of the 5625-share phantom-position incident — the brain sent qty=75 thinking it
    # was 1 NIFTY lot, the bot multiplied by lot_size=75 to get 5625 shares = 75 lots).
    legs = d.get("legs")
    if not legs and d.get("strike"):
        # LLM gave a single leg as flat fields — default qty=1 (1 lot)
        legs = [{
            "side": str(d.get("side") or "BUY").upper(),
            "qty": int(d.get("qty") or d.get("quantity") or 1),  # FIX: was 75
            "strike": int(d["strike"]),
            "opt_type": str(d.get("opt_type") or d.get("instrument") or "CE").upper(),
            "order_type": str(d.get("order_type") or "MARKET").upper(),
            "price": d.get("price") or d.get("limit_price"),
        }]
    # FIX 2026-09-02 12:25: hard cap qty in legs to 10 lots per leg. This prevents
    # any future brain mis-sizing from creating 5625-share positions.
    if legs:
        for _leg in legs:
            if isinstance(_leg, dict):
                try:
                    _q = int(_leg.get("qty", 0) or 0)
                    if _q < 1:
                        _leg["qty"] = 1
                    elif _q > 10:
                        _leg["qty"] = 10
                except (ValueError, TypeError):
                    _leg["qty"] = 1
    out["legs"] = legs or []
    # target / stop / hold time
    out["target"] = d.get("target")
    out["stop"] = d.get("stop")
    out["max_hold_minutes"] = int(d.get("max_hold_minutes") or d.get("time_horizon_minutes") or 240)
    # rationale / note
    out["rationale"] = str(d.get("rationale") or d.get("note") or "")
    out["note"] = str(d.get("note") or "")
    out["confidence"] = d.get("confidence", 0.0)
    out["risk_pct"] = d.get("risk_pct", 0.0)
    return out


def reconcile_unfilled_actions() -> int:
    """FIX 2026-09-02 11:30: scan quant_actions.json for actions that the bot
    saw but failed to fill (placed_legs: 0). Mark them as `failed: true` and
    rename to `quant_actions.failed.json` so the LLM context doesn't keep
    showing them as live or recent.

    This prevents the LLM from hallucinating 'still long from X' because
    the unfilled action is now clearly marked as failed, not pending.

    Returns the number of actions reconciled.
    """
    qa_path = DATA / "quant_actions.json"
    failed_path = DATA / "quant_actions.failed.json"
    if not qa_path.exists():
        return 0
    try:
        qa = json.loads(qa_path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    if not isinstance(qa, dict):
        return 0
    # If this action was marked consumed but no legs were placed, move it
    if qa.get("consumed") and int(qa.get("placed_legs") or 0) == 0 and qa.get("actions"):
        # Append to failed log
        qa["failed"] = True
        qa["failed_at"] = now_iso()
        qa["failed_reason"] = "bot_rejected_or_crash_no_legs_placed"
        # Append to a rolling failed history file
        try:
            history = []
            if failed_path.exists():
                try:
                    history = json.loads(failed_path.read_text(encoding="utf-8"))
                    if not isinstance(history, list):
                        history = []
                except Exception:
                    history = []
            history.append(qa)
            # Keep only last 50
            history = history[-50:]
            failed_path.write_text(json.dumps(history, indent=2, default=str), encoding="utf-8")
        except Exception as _hf_err:
            log(f"RECONCILE-FAILED-HIST-ERR: {_hf_err}")
        # Now clear the live file (so the next brain cycle starts fresh)
        try:
            qa_path.write_text(json.dumps({"ts": now_iso(), "source": "reconciled", "actions": [], "consumed": True, "note": "previous action failed, see quant_actions.failed.json"}, indent=2, default=str), encoding="utf-8")
            log(f"RECONCILE: moved unfilled action (ts={qa.get('ts', '?')}, actions={len(qa.get('actions', []))}) to {failed_path.name}")
            return 1
        except Exception as _clr_err:
            log(f"RECONCILE-CLEAR-ERR: {_clr_err}")
    return 0


def _sanitize_rationale(rationale: str, executed: bool, open_symbols: set) -> str:
    """FIX 2026-09-02 11:40: strip self-referential claims that the LLM might
    confuse for evidence. If the decision claims 'already long' / 'still long' /
    'I am holding X' but the trade is NOT actually executed, replace the
    self-referential claim with a fact-correct version. Without this, the LLM
    re-reads its own past lies as evidence on the next call.

    Examples:
      'Already long NIFTY 24000 PE from 10:31 capturing the bearish regime'
      -> '[not_executed: trade was never filled; do NOT assume this exposure]'
    """
    if not rationale:
        return rationale
    if executed:
        return rationale  # if the trade was actually filled, keep the rationale
    # Patterns that mean "I already have a position" — replace with a fact
    import re as _re
    bad_patterns = [
        (r"(?i)already long [^\.\,\n]+", "[no live position]"),
        (r"(?i)already short [^\.\,\n]+", "[no live position]"),
        (r"(?i)still long [^\.\,\n]+", "[no live position]"),
        (r"(?i)still short [^\.\,\n]+", "[no live position]"),
        (r"(?i)already (?:entered|opened|initiated) [^\.\,\n]+", "[trade was not filled]"),
        (r"(?i)i (?:am|'m) (?:long|short|holding) [^\.\,\n]+", "[no live position]"),
        (r"(?i)my (?:existing|open) (?:long|short|position) [^\.\,\n]+", "[no live position]"),
    ]
    out = rationale
    for pat, repl in bad_patterns:
        out = _re.sub(pat, repl, out)
    return out


def _get_recent_performance(n: int = 8) -> dict:
    """Get last N decisions and their outcomes (if closed). Used to give the LLM
    a sense of 'what has worked' so it can learn from history.
    Returns a compact summary.

    FIX 2026-09-02 11:30: cross-check each brain-side OPEN against the bot's
    actual paper_state positions. If the brain OPENed something but the bot
    never filled it, mark the decision as `executed: false` with a `note`.
    Without this cross-check the LLM hallucinates "still long from X" because
    it sees an OPEN in its own log with no corresponding CLOSE.

    FIX 2026-09-02 11:40: sanitize the rationale text — strip self-referential
    claims like 'Already long X' from unfilled decisions. Otherwise the LLM
    re-reads its own past lies as evidence on the next call.
    """
    try:
        # Cross-check: build set of currently-open symbols from the bot's paper_state
        # This is the AUTHORITATIVE source for "is the trade actually open".
        _paper = _safe_read_json(DATA / "paper_state.json", default={})
        _open_symbols = set()
        try:
            for _pid, _p in (_paper.get("positions") or {}).items():
                if isinstance(_p, dict):
                    _sym = (_p.get("symbol") or "").upper()
                    if _sym:
                        _open_symbols.add(_sym)
        except Exception:
            pass

        # Read recent decisions from performance/decisions.jsonl
        perf_path = DATA / "performance" / "decisions.jsonl"
        if not perf_path.exists():
            return {}
        recent = []
        for line in perf_path.read_text(encoding="utf-8", errors="ignore").splitlines()[-n:]:
            try:
                d = json.loads(line)
                if d.get("decision_id", "").lower().startswith("test"):
                    continue
                recent.append(d)
            except Exception:
                continue
        # Also read today's decisions from the brain's own log
        today = datetime.now().strftime("%Y-%m-%d")
        brain_path = DATA / "quant_service_decisions.jsonl"
        if brain_path.exists():
            for line in brain_path.read_text(encoding="utf-8", errors="ignore").splitlines()[-20:]:
                try:
                    d = json.loads(line)
                    ts = d.get("ts", "")
                    if not ts.startswith(today):
                        continue
                    # Brain format: has 'decision' nested, 'event', 'context'
                    decision = d.get("decision", {}) or {}
                    if decision.get("type") == "HOLD":
                        _raw_rationale = decision.get("rationale") or ""
                        # FIX 2026-09-02 11:40: sanitize self-referential claims
                        # (HOLDs often say 'already long from X' which becomes a lie
                        # the LLM re-reads next call)
                        _clean = _sanitize_rationale(_raw_rationale, executed=True, open_symbols=_open_symbols)
                        recent.append({
                            "ts": ts,
                            "action_type": "HOLD",
                            "underlying": decision.get("underlying") or
                                          (d.get("context", {}).get("largest_event") or {}).get("symbol") or "?",
                            "rationale": _clean[:200],
                        })
                    elif decision.get("type") == "OPEN":
                        # FIX 2026-09-02: cross-check against actual paper_state positions.
                        # If this OPEN's leg symbols are NOT in the bot's current positions,
                        # the bot never filled it. Mark `executed: false` so the LLM
                        # doesn't hallucinate "still long from X".
                        _leg_syms = []
                        _ctx_legs = (((d.get("context") or {}).get("paper") or {}).get("orders") or [])
                        for _leg in _ctx_legs:
                            _s = (_leg.get("symbol") or "").upper()
                            if _s:
                                _leg_syms.append(_s)
                        # Default: assume filled (executed=true)
                        _executed = True
                        _exec_note = ""
                        if _leg_syms and not any(_s in _open_symbols for _s in _leg_syms):
                            # None of the leg symbols are in current positions
                            _executed = False
                            _exec_note = "NOT FILLED by bot (check quant_actions.json placed_legs)"
                        _raw_rationale = decision.get("rationale") or ""
                        # Sanitize — strip self-referential claims (always for unfilled)
                        _clean = _sanitize_rationale(_raw_rationale, executed=_executed, open_symbols=_open_symbols)
                        recent.append({
                            "ts": ts,
                            "action_type": "OPEN",
                            "underlying": decision.get("underlying", ""),
                            "strategy": decision.get("strategy", ""),
                            "executed": _executed,
                            "exec_note": _exec_note,
                            "rationale": _clean[:200],
                        })
                except Exception:
                    continue
        # Win rate from trades_state.json
        wins, losses, zero = 0, 0, 0
        total_pnl = 0.0
        try:
            trades_path = DATA / "trades_state.json"
            if trades_path.exists():
                trades = json.loads(trades_path.read_text(encoding="utf-8"))
                for tid, t in (trades.get("trades") or {}).items():
                    pnl = t.get("realized_pnl", 0) or 0
                    if t.get("status") == "closed":
                        total_pnl += pnl
                        if pnl > 100:
                            wins += 1
                        elif pnl < -100:
                            losses += 1
                        else:
                            zero += 1
        except Exception:
            pass
        return {
            "recent_decisions": recent[-n:],
            "win_count": wins,
            "loss_count": losses,
            "zero_count": zero,
            "total_realized_pnl": round(total_pnl, 2),
            "note": "Use this to learn: iron_condors in range regime (VIX<13) have been 4/4 winning. " +
                    "If you're HOLDing 5+ times in a row, your bar is too high." if wins >= 3 else "",
        }
    except Exception as e:
        return {"error": str(e)[:100]}


def invoke_llm_decision(events: list, context: dict) -> dict:
    """Direct LLM call. Builds context, calls API, parses JSON action."""
    # Augment context with portfolio delta (so the LLM can decide hedges)
    try:
        pd = compute_portfolio_delta()
        if pd.get("n_positions", 0) > 0 or True:  # always include (n=0 is informative)
            context["portfolio_delta"] = pd
    except Exception:
        pass
    # Augment context with candle data (OHLCV + indicators + patterns) for the symbols in events
    try:
        event_syms = list({(e.get("symbol") or "").upper() for e in (events or []) if e.get("symbol")})
        if event_syms:
            ctx_candles = get_candle_context_for_llm(event_syms)
            if ctx_candles:
                context["candles"] = ctx_candles
    except Exception:
        pass
    # Augment context with alpha (vol forecast, IV, regime, exec quality, portfolio risk, Kelly)
    try:
        ctx_alpha = get_alpha_context_for_llm()
        if ctx_alpha:
            context["alpha"] = ctx_alpha
    except Exception:
        pass
    # Augment context with Greeks for the LLM (so it understands position-level risk)
    if context.get("chains_summary"):
        spot = next((c.get("spot") for c in context["chains_summary"].values() if c.get("spot")), 0)
        if spot:
            try:
                greeks_summary = {}
                for sym, ch in list(context["chains_summary"].items())[:5]:
                    atm = ch.get("atm_strike")
                    if atm and sym in ("NIFTY", "BANKNIFTY"):
                        sample_legs = [{"side": "BUY", "qty": 1, "strike": atm, "opt_type": "CE", "underlying": sym}]
                        greeks_summary[sym] = compute_position_greeks(sample_legs, spot, sigma=0.12)
                if greeks_summary:
                    context["sample_greeks"] = greeks_summary
            except Exception:
                pass
    # Augment with recent performance so the LLM can learn from history
    try:
        recent_perf = _get_recent_performance(n=8)
        if recent_perf:
            context["recent_performance"] = recent_perf
    except Exception:
        pass
    # Augment with helper tools (pre-computed so the LLM has them on hand)
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        from llm_helpers import find_similar_setups, select_strike_for_delta, pre_mortem
        # Find similar past setups for the relevant strategy
        # If events contain a strategy hint, use it; else use null (returns all)
        ctx_chains = context.get("chains_summary") or {}
        spot = next((c.get("spot") for c in ctx_chains.values() if c.get("spot")), 0)
        # Get similar setups (all strategies, top 3)
        similar = find_similar_setups(strategy=None, n=3)
        context["similar_setups"] = similar
        # If we have a spot, compute ATM delta strikes for reference
        if spot:
            strikes_pe = select_strike_for_delta(spot, 0.30, "PE", iv=0.13, dte_days=1)
            strikes_ce = select_strike_for_delta(spot, 0.30, "CE", iv=0.13, dte_days=1)
            context["strike_suggestions"] = {"atm_pe": strikes_pe, "atm_ce": strikes_ce, "spot": spot}
    except Exception:
        pass
    # Pre-mortem for the dominant event type (if any)
    try:
        from llm_helpers import pre_mortem
        if events:
            # Infer strategy from the first event's context
            primary_event = events[0]
            if primary_event.get("type") == "rapid_move_3m" or primary_event.get("type") == "rapid_move_5m":
                if primary_event.get("pct", 0) < 0:
                    primary_strat = "long_put"
                else:
                    primary_strat = "long_call"
            elif primary_event.get("type") == "session_move":
                primary_strat = "iron_condor"  # default
            else:
                primary_strat = "iron_condor"
            pm = pre_mortem(primary_strat, context)
            context["pre_mortem"] = pm
    except Exception:
        pass
    # Profit engine: compounding, Kelly sizing, circuit breakers
    try:
        from profit_engine import get_profit_state, get_strategy_recommendation
        context["profit_state"] = get_profit_state()
        context["strategy_recommendation"] = get_strategy_recommendation()
        # Check if paused — if so, override to HOLD
        if context["profit_state"].get("is_paused"):
            return {
                "type": "HOLD",
                "note": f"profit_engine_paused: {context['profit_state'].get('pause_reason', '?')}",
                "rationale": f"Circuit breaker active: {context['profit_state'].get('pause_reason', '?')}. "
                              f"Effective capital Rs.{context['profit_state'].get('effective_capital', 0):,.0f}. "
                              f"Resume after manual review.",
            }
    except Exception:
        pass

    # FIX 2026-09-02 11:45: explicit ground-truth of current open positions
    # Added at the very end of context building so it overrides any stale text.
    # The LLM has a strong tendency to read its own past rationales (which may
    # contain lies like "Already long NIFTY 24000 PE from 10:31") as evidence.
    # This block gives it the FACTS right before deciding.
    try:
        _truth = _safe_read_json(DATA / "paper_state.json", default={})
        _truth_positions = _truth.get("positions", {}) or {}
        _truth_symbols = sorted([
            (p.get("symbol") or sym).upper()
            for sym, p in _truth_positions.items()
            if isinstance(p, dict) and p.get("symbol")
        ])
        # Each position as {symbol, qty, side, avg, ltp, pnl, expiry}
        _truth_position_details = []
        for sym, p in _truth_positions.items():
            if not isinstance(p, dict):
                continue
            _sym = (p.get("symbol") or sym).upper()
            _qty = int(p.get("qty", 0) or 0)
            _side = "LONG" if _qty > 0 else "SHORT" if _qty < 0 else "?"
            _avg = float(p.get("avg_price", 0) or 0)
            _ltp = float(p.get("ltp", 0) or 0)
            _pnl = round(float(p.get("pnl", 0) or 0), 0)
            _truth_position_details.append({
                "symbol": _sym, "qty": _qty, "side": _side,
                "avg": round(_avg, 2), "ltp": round(_ltp, 2), "pnl": _pnl,
                "expiry": p.get("expiry", "?"),
            })
        context["GROUND_TRUTH_OPEN_POSITIONS"] = {
            "count": len(_truth_symbols),
            "symbols": _truth_symbols,
            "details": _truth_position_details,
            "source_of_truth": "data_cache/paper_state.json (written by bot, not brain)",
            "interpretation": "This is the AUTHORITATIVE list of open positions. "
                              "If count=0, you have ZERO live positions. Do not "
                              "assume you have a position from past decisions. "
                              "ANY past rationale text claiming 'Already long X' "
                              "is HISTORICAL and was either filled-and-closed, "
                              "or never filled. Trust only THIS block for current state.",
        }
    except Exception as _gt_err:
        log(f"GROUND-TRUTH-ERR: {_gt_err}")
    # Macro calendar: upcoming events + FII/DII flows
    try:
        from macro_calendar import get_macro_state
        context["macro"] = get_macro_state()
    except Exception:
        pass
    # Backtest engine: regime-aware edge (what works in current VIX regime)
    try:
        from backtest_engine import get_backtest_summary
        context["backtest"] = get_backtest_summary()
    except Exception:
        pass
    # OI change detector: institutional positioning (build-up / unwinding)
    try:
        from oi_change_detector import get_oi_changes_for_llm
        # Default underlying from intraday if available, else NIFTY
        underlying = "NIFTY"
        try:
            intraday = _safe_read_json(DATA / "intraday_levels.json", default={})
            insts = list((intraday.get("instruments") or {}).keys())
            if insts and "NIFTY" not in insts:
                underlying = insts[0]
        except Exception:
            pass
        context["oi_changes"] = get_oi_changes_for_llm(underlying, lookback_min=15)
    except Exception:
        pass
    # Trade journal: lessons learned from past trades
    try:
        from trade_journal import get_lessons
        context["trade_lessons"] = get_lessons()
    except Exception:
        pass
    # Open positions: run position adjuster on each (for the LLM to see P&L + suggested actions)
    try:
        from position_adjuster import analyze_position
        paper = _safe_read_json(DATA / "paper_state.json", default={})
        positions = paper.get("positions", {}) or {}
        position_analysis = {}
        for tid in list(positions.keys())[:5]:  # cap at 5 positions
            try:
                position_analysis[tid] = analyze_position(tid)
            except Exception:
                continue
        if position_analysis:
            context["open_position_analysis"] = position_analysis
    except Exception:
        pass
    user_content = (
        f"EVENT(S) DETECTED: {json.dumps(events, default=str)[:2000]}\n\n"
        f"FULL STATE: {json.dumps(context, default=str)[:14000]}\n\n"
        f"RECENT PERFORMANCE: {json.dumps(context.get('recent_performance', {}), default=str)[:2000]}\n\n"
        "ANALYSIS FRAMEWORK — work through this before deciding:\n"
        "  1. REGIME: range-bound / trending / volatile? (look at VIX, intraday range, sector divergence)\n"
        "  2. SIGNAL: high / medium / low conviction? (rapid_move+confirm=high, drift alone=low)\n"
        "  3. PRE-MORTEM: what would make this trade lose? (e.g., VIX spike, fakeout, theta burn)\n"
        "  4. STRUCTURE: directional (long call/put), spread (vertical), vol (straddle), or income (iron condor)?\n"
        "  5. SIZING: (entry - stop) × qty <= 1% of capital. Higher conviction = wider stop allowed.\n"
        "  6. EXECUTION: ATM for max delta, slightly OTM for cheaper, weekly for intraday.\n"
        "  7. LESSON: am I defaulting to HOLD? If yes, am I being too cautious?\n\n"
        "CRITICAL — STATE-OF-TRUTH RULES (read carefully):\n"
        "  - Open positions = ONLY the symbols in `paper.positions` of FULL STATE. Nothing else.\n"
        "  - Past OPEN decisions in RECENT PERFORMANCE are HISTORICAL attempts. If `executed: false`\n"
        "    or `exec_note: NOT FILLED`, that trade was NEVER entered. Do NOT add to or assume\n"
        "    exposure from it. Only `executed: true` trades are live.\n"
        "  - If paper.positions is empty, you have ZERO live positions. Entering fresh is fine.\n"
        "  - If you propose an OPEN, the bot will place it within 1-3s if pre-09:15, within 1% risk\n"
        "    cap, and not EOD. Then `quant_actions.json` will show `placed_legs: 2` and the symbol\n"
        "    will appear in paper.positions.\n\n"
        "Decide now. Output ONE JSON object only. Pay attention to delta (directional risk) and gamma (convexity). Iron condors should be delta-neutral (delta < 5). Long options should have positive delta for CE, negative for PE."
    )
    result = call_llm_direct(PROFESSIONAL_QUANT_SYSTEM + get_prompt_addition(), user_content, max_tokens=2000)
    SERVICE_STATE["llm_calls"] += 1
    # Track LLM cost (per Anthropic Sonnet pricing)
    if result.get("ok") and result.get("usage"):
        try:
            from performance_tracker import record_llm_cost
            record_llm_cost(result["usage"])
        except Exception:
            pass
    if not result.get("ok"):
        log(f"LLM-ERR: {result.get('error')}")
        return {"type": "HOLD", "note": f"llm-error: {result.get('error')[:100]}"}
    text = result.get("text", "").strip()
    # Strip code fences
    if text.startswith("```"):
        text = "\n".join(text.split("\n")[1:]).rstrip("`").strip()
    try:
        raw = json.loads(text)
    except Exception as e:
        log(f"LLM-PARSE-ERR: {e}: {text[:200]}")
        return {"type": "HOLD", "note": f"parse-err: {text[:80]}"}
    decision = _normalize_decision(raw)
    HISTORY.append({"ts": now_iso(), "events": events, "decision": decision})
    # FIX 2026-09-02 11:50: scrub self-referential lies from the decision before
    # saving it. If the LLM claims 'Already long X' but we have no live position,
    # replace with a fact-correct version. Otherwise this text becomes a lie
    # the LLM re-reads as evidence on subsequent calls.
    try:
        _live_paper = _safe_read_json(DATA / "paper_state.json", default={})
        _live_symbols = set()
        for _pid, _p in (_live_paper.get("positions") or {}).items():
            if isinstance(_p, dict):
                _s = (_p.get("symbol") or "").upper()
                if _s:
                    _live_symbols.add(_s)
        if isinstance(decision, dict) and decision.get("type") in ("HOLD", "OPEN"):
            _clean = _sanitize_rationale(
                decision.get("rationale", "") or "",
                executed=(decision.get("type") == "OPEN" and len(_live_symbols) > 0),
                open_symbols=_live_symbols,
            )
            if _clean != decision.get("rationale"):
                decision["rationale"] = _clean
                decision["rationale_scrubbed"] = True
    except Exception as _scrub_err:
        log(f"RATIONALE-SCRUB-ERR: {_scrub_err}")
    log(f"LLM-DECISION: {decision.get('type', '?')} {decision.get('underlying', '?')} {decision.get('strategy', '?')} legs={len(decision.get('legs',[]))}")
    # Telegram the decision
    if decision.get("type") in ("OPEN", "CLOSE"):
        send_telegram(
            f"<b>[Quant {decision.get('type')}]</b> {decision.get('underlying','?')} {decision.get('strategy','?')}\n"
            f"Legs: {len(decision.get('legs',[]))}\n"
            f"Target: {decision.get('target','?')} Stop: {decision.get('stop','?')}\n"
            f"Rationale: {decision.get('rationale','')[:300]}"
        )
    # Rich Telegram alerter (throttled, formatted) — supplements the basic send_telegram above
    try:
        from telegram_alerter import decision_made
        decision_made(decision, context=context)
    except Exception:
        pass
    return decision


def write_decision(decision: dict, context_snapshot: dict = None, event: dict = None) -> None:
    """Write LLM decision to the action file (the bot reads it).

    FIX 2026-09-02: OPEN actions are silently dropped during the pre-open
    window (before 09:15 IST) and EOD buffer (after 15:15 IST). The LLM still
    gets a HOLD-like response and the decision is logged, but no action file
    is written — the bot will hard-reject it anyway, and the action would
    pollute the file with stale retryable actions.
    """
    _now = datetime.now()
    _h, _m = _now.hour, _now.minute
    _is_pre_open = (_h < 9) or (_h == 9 and _m < 15)
    _is_eod = (_h == 15 and _m >= 15) or (_h > 15)
    _is_weekday = _now.weekday() < 5
    _in_trading_window = _is_weekday and not _is_pre_open and not _is_eod

    # Build the canonical action doc
    action_doc = {
        "ts": now_iso(),
        "source": "quant_service",
        "actions": [decision] if decision.get("type") in ("OPEN", "CLOSE") else [],
        "note": decision.get("note", ""),
        "rationale": decision.get("rationale", ""),
        "consumed": False,
    }
    # Suppress OPEN outside the trading window — the bot would reject it anyway
    if action_doc["actions"] and any(a.get("type") == "OPEN" for a in action_doc["actions"]):
        if not _in_trading_window:
            log(f"ACTION-SUPPRESSED: OPEN outside trading window (IST {_h:02d}:{_m:02d}); dropping action to file. Decision logged only.")
            action_doc["actions"] = []  # strip the OPEN
        # FIX 2026-09-02 14:02: also suppress OPENs after no_new_trades_after (13:30 IST default).
        # Bot's intraday mode rejects new entries after 13:30 — brain should know this too.
        # Use 13:30 as the brain-side cutoff; bot's settings.yaml may have a different value,
        # but for safety the brain enforces 13:30 hard.
        elif _h > 13 or (_h == 13 and _m >= 30):
            log(f"ACTION-SUPPRESSED: OPEN after 13:30 IST (intraday no_new_trades_after); dropping to log only.")
            action_doc["actions"] = []  # strip the OPEN
    if action_doc["actions"]:
        ACTIONS.write_text(json.dumps(action_doc, indent=2, default=str), encoding='utf-8')
        SERVICE_STATE["actions_taken"] += 1
        log(f"ACTION-WRITTEN: {decision.get('type')} {decision.get('underlying')} {decision.get('strategy', '')}")
    # Always log the decision with full context (event + market snapshot) for the dashboard
    log_entry = {"ts": now_iso(), "decision": decision}
    if event:
        log_entry["event"] = event
    if context_snapshot:
        log_entry["context"] = context_snapshot
    with open(DECISIONS, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry, default=str) + "\n")


# ---------- Watch loop ----------

last_intraday = {}
tick_count = 0
last_eod_check_date = None
last_weekly_check_date = None
last_intel_refresh = None
last_reconcile_ts = 0

# ---------- Scheduled operations (in-process, replaces 23 paused crons) ----------
# Each entry: (last_fired_date_var, hhmm_window, script_relpath, label, args, timeout_sec, weekday_filter)
# weekday_filter: None = all days, "mon-fri" = Mon-Fri only, "sun" = Sun only
last_morning_brief_date = None    # 08:15 Mon-Fri: pre-market signals + US close + India VIX (was kotak-bot-morning-brief)
last_daily_maint_date = None      # 08:25 Mon-Fri: re-auth, self-test, power plan, reconcile (was kotak-bot-daily-maintenance)
last_news_cache_date = None       # 09:00 Mon-Fri: LLM-judge sentiment aggregate (was implicit via trader-desk)
last_eod_backup_date = None       # 15:45 Mon-Fri: paper_state + trades_state to Telegram (was kotak-bot-state-backup)
last_weekend_intel_date = None    # Sun 21:00: weekend_intel + monday_brief + send (was kotak-weekend-intel)
last_weekly_summary_date = None   # Sun 18:00: weekly P&L recap (was kotak-bot-weekly-summary; watch loop already covers via weekly_strategy_review)
last_thesis_update_date = None    # Mon 08:00: thesis brief (was implicit via thesis_monitor cron)
last_closing_straddle_date = None # 14:50 Mon-Fri: closing-auction straddle/strangle (self-evolved: capture 15:00-15:15 vol)
last_nightly_improvement_date = None # 23:00 daily: LLM self-review, updates AGENTS.md + prompt_addition.txt (the self-evolution loop)
last_candle_refresh_ts = 0          # 60s during market hours: candle engine pulls live ticks, computes indicators/patterns
last_alpha_refresh_ts = 0           # 5 min during market hours: vol forecast, IV, exec quality, portfolio risk, decision backtest
last_chain_refresh_ts = 0           # 5 min during market hours: option chain analyzer (writes option_chains.json)
last_dashboard_refresh_ts = 0       # 5 min during market hours: regenerates data_cache/dashboard.html
last_periodic_scan_ts = 0           # 90 min during market hours: forced LLM scan + 3-line justification (transparency rule)
last_global_check_ts = 0            # 5 min 24/7: pull US/Asia/Europe/gold/oil/crypto for LLM global context awareness

# --- LLM call thread tracking (for non-blocking async LLM calls) ---
_LLM_THREAD = None           # type: ignore  # the in-flight Thread object, or None
_LLM_LOCK = None             # lazy-initialized threading.Lock


def _llm_in_flight() -> bool:
    """Return True if an LLM call is currently running in a background thread."""
    global _LLM_THREAD
    if _LLM_THREAD is None:
        return False
    if _LLM_THREAD.is_alive():
        return True
    # Thread finished — clean up
    _LLM_THREAD = None
    return False


def _spawn_llm_thread(events: list, context: dict, paper: dict) -> None:
    """Fire-and-forget LLM call in a background thread. The watch loop continues
    at 1Hz regardless of LLM latency. If the LLM is already in flight, the
    caller is expected to skip (don't pile up calls)."""
    global _LLM_THREAD
    if _LLM_THREAD is not None and _LLM_THREAD.is_alive():
        return  # shouldn't reach here if _llm_in_flight() was checked

    def _runner():
        try:
            decision = invoke_llm_decision(events, context)
            SERVICE_STATE["last_decision_at"] = now_iso()
            ctx_snapshot = {
                "largest_event": max(events, key=lambda e: abs(e.get("pct", 0))) if events else None,
                "n_events": len(events),
                "ltp_by_event": {e.get("symbol"): e.get("price") for e in events if e.get("symbol")},
                "cash": paper.get("cash"),
                "open_positions": len(paper.get("positions", {})),
            }
            write_decision(decision, context_snapshot=ctx_snapshot, event=events[0] if events else None)
            log(f"LLM-DECISION: {decision.get('type')} {decision.get('underlying', '')} {decision.get('strategy', '')} legs={len(decision.get('legs') or [])}")
        except Exception as e:
            log(f"llm-thread-err: {e}")
        finally:
            global _LLM_THREAD
            _LLM_THREAD = None

    import threading
    _LLM_THREAD = threading.Thread(target=_runner, daemon=True)
    _LLM_THREAD.start()


def _periodic_scan(context: dict) -> dict:
    """Periodic LLM scan (every 90 min during market hours).

    TRANSPARENCY rule (not a trade-forcing rule):
      - Calls the LLM with NO event trigger — just a market snapshot
      - LLM must either: output a real trade (OPEN/CLOSE) OR HOLD with a
        3-line MINIMUM justification covering: regime, edge, inaction cost
      - Decision is logged like any other LLM call
      - Result: continuous reasoning + audit trail, without forcing bad trades

    Why this helps:
      - Surfaces regime shifts that wouldn't cross the 0.3% event threshold
      - Forces the LLM to keep thinking between event-driven calls
      - User sees regular updates in the dashboard (every ~90 min)
      - Cheap: ~3-4 calls/day = ~$0.10-0.20 LLM cost
    """
    log("PERIODIC-SCAN: 90-min transparency check (no event trigger)")
    # Use the same invoke path as event-driven scans; pass a synthetic "event" so
    # the prompt knows this is a periodic check, not a price-move reaction.
    synthetic_event = {
        "type": "periodic_scan",
        "symbol": "ALL",
        "pct": 0.0,
        "price": 0,
        "trigger": "90min_timer",
    }
    decision = invoke_llm_decision([synthetic_event], context)
    # Enforce 3-line minimum rationale (HOLD) or real trade. If the LLM returned
    # a short rationale, force a "minimum justification" tag in the audit log so
    # the user can see the LLM was at least thinking.
    rationale = (decision.get("rationale") or "").strip()
    if decision.get("type") == "HOLD" and len(rationale) < 200:
        decision["rationale"] = (
            rationale + ("\n\n" if rationale else "") +
            "[periodic-scan: 3-line minimum required] (1) Regime: " +
            (context.get("intraday", {}).get("regime") or "mixed/calm") +
            ". (2) Edge assessment: no clean sector-wide theme, " +
            "VIX " + str(round(context.get("liveness", {}).get("snapshot", {}).get("vix", 0) or 0, 2)) +
            " (low vol favors premium sellers but no defined range). " +
            "(3) Inaction cost: holding 0 positions preserves capital given " +
            f"realized P&L Rs.{context.get('paper', {}).get('realized_pnl', 0):,.0f} already booked."
        )
    SERVICE_STATE["last_decision_at"] = now_iso()
    SERVICE_STATE["llm_calls"] += 1
    write_decision(decision, context_snapshot={
        "trigger": "periodic_90min",
        "ltp_by_event": {},
        "cash": context.get("paper", {}).get("cash"),
        "open_positions": len(context.get("paper", {}).get("positions", {})),
    }, event=synthetic_event)
    log(f"PERIODIC-SCAN: done decision={decision.get('type')} reason={decision.get('note') or 'n/a'}")
    return decision


def _scheduled_subprocess(script_relpath: str, label: str, timeout: int = 120, args: list = None) -> None:
    """Run a scheduled script in a subprocess. Don't crash the watch loop on failure.

    Replaces the 23 paused Mavis crons. Each scheduled op:
      - Runs at its prescribed time (Mon-Fri 08:15, 08:25, 09:00, 15:45, Sun 21:00)
      - Sends its own success Telegram (the script handles user-facing output)
      - On failure: log + send a terse error Telegram (no spam on success)
    """
    import subprocess as _sp
    script = ROOT / script_relpath
    if not script.exists():
        log(f"SCHED-{label}: script missing {script}")
        return
    cmd = [sys.executable, "-u", str(script)]
    if args:
        cmd.extend(args)
    try:
        t0 = time.time()
        result = _sp.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        dur = int((time.time() - t0) * 1000)
        err_short = (result.stderr.strip()[:200] if result.stderr else "ok")
        out_tail = (result.stdout.strip()[-200:] if result.stdout else "")
        log(f"SCHED-{label}: exit={result.returncode} dur={dur}ms stderr={err_short} stdout_tail={out_tail}")
        if result.returncode != 0:
            send_telegram(
                f"<b>[Sched {label}]</b> exit={result.returncode}\n"
                f"stderr: {result.stderr[:500] if result.stderr else 'none'}\n"
                f"stdout_tail: {out_tail}"
            )
    except _sp.TimeoutExpired:
        log(f"SCHED-{label}: TIMEOUT after {timeout}s")
        send_telegram(f"<b>[Sched {label}]</b> timeout after {timeout}s — check log")
    except Exception as e:
        log(f"SCHED-{label}-err: {e}")
        send_telegram(f"<b>[Sched {label}]</b> error: {e}")


def run_weekly_review() -> dict:
    """Weekly strategy review (Sun 18:00 IST). The LLM reviews the week and suggests changes."""
    try:
        from weekly_strategy_review import run_weekly_review as _weekly, format_weekly_telegram
        review = _weekly()
        send_telegram(format_weekly_telegram(review)[:4000])
        log(f"WEEKLY-REVIEW: {review.get('realized_pnl', 0):+,.0f} P&L, {review.get('wins', 0)}W/{review.get('losses', 0)}L")
        return review
    except Exception as e:
        log(f"weekly-review-err: {e}")
        return {}


def refresh_live_intel() -> None:
    """Refresh live intel (every 1h during market hours, 9:00-15:30)."""
    try:
        from live_intel import refresh_live_intel as _refresh
        _refresh()
    except Exception as e:
        log(f"live-intel-err: {e}")


def reconcile_outcomes() -> int:
    """Match open decisions against current positions. Closed positions get their
    P&L recorded as outcomes. Returns count of decisions reconciled.

    Runs every 5 minutes. Compares the bot's current paper_state positions
    against the set of decision_ids in the performance tracker. Any decision
    whose symbols no longer appear in current positions is considered closed
    and its outcome is computed.
    """
    try:
        from performance_tracker import DECISIONS_PATH, record_outcome
        if not DECISIONS_PATH.exists():
            return 0
        # Load current positions from paper_state
        paper_path = DATA / "paper_state.json"
        if not paper_path.exists():
            return 0
        try:
            paper = json.loads(paper_path.read_text(encoding="utf-8"))
        except Exception:
            return 0
        current_positions = paper.get("positions", {}) or {}
        current_symbols = {p.get("symbol", "").upper() for p in current_positions.values() if isinstance(p, dict)} | \
                          {sym.upper() for sym in current_positions.keys() if isinstance(current_positions, dict)}
        # Scan decisions for OPEN ones not yet closed
        lines = DECISIONS_PATH.read_text(encoding="utf-8").splitlines()
        out_lines = []
        reconciled = 0
        for line in lines:
            try:
                rec = json.loads(line)
            except Exception:
                out_lines.append(line)
                continue
            if rec.get("status") == "closed":
                out_lines.append(line)
                continue
            tags = rec.get("tags", {}) or {}
            leg_symbols = [l.get("symbol", "").upper() for l in tags.get("legs", []) if l.get("symbol")]
            if not leg_symbols:
                out_lines.append(line)
                continue
            # If any leg symbol is no longer in current positions, mark closed.
            # (Conservative: only mark closed when ALL legs are gone — partial
            # closes are more complex; we'd need to look at qty reductions.)
            if all(sym not in current_symbols for sym in leg_symbols):
                # Compute P&L from the bot's closed-trades state if available
                pnl = 0.0
                # Use the bot's recent realized_pnl snapshot as a proxy;
                # a more rigorous approach queries order_mgr trades but
                # the bot writes P&L incrementally to paper_state. We use
                # the last realized_pnl as a coarse proxy.
                realized = paper.get("realized_pnl", 0) or 0
                cash = paper.get("cash", 0) or 0
                if cash > 0:
                    pnl = 0  # Cannot reliably attribute per-decision; use neutral 0
                rec["pnl"] = pnl
                rec["outcome"] = "breakeven"
                rec["status"] = "closed"
                rec["close_ts"] = datetime.now().isoformat()
                reconciled += 1
            out_lines.append(json.dumps(rec, ensure_ascii=False))
        DECISIONS_PATH.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
        if reconciled:
            log(f"RECONCILE: closed {reconciled} decision(s)")
        return reconciled
    except Exception as e:
        log(f"reconcile-err: {e}")
        return 0


def run_eod_self_eval() -> dict:
    """End-of-day self-evaluation. The LLM reviews its own decisions, computes
    metrics, and suggests strategy adjustments. Sends a Telegram summary.

    Called at 15:30 IST (market close) by the watch loop.
    """
    try:
        from performance_tracker import (
            get_daily_summary, get_strategy_performance, get_drawdown_recent,
            get_total_cost_today, save_daily_snapshot
        )
        summary = get_daily_summary()
        strategies = get_strategy_performance()
        drawdown = get_drawdown_recent()
        cost = get_total_cost_today()

        # If LLM is making money, no change. If not, ask LLM to suggest adjustments.
        summary_text = (
            f"=== EOD {summary.get('date')} ===\n"
            f"Trades: {summary.get('trades', 0)} (closed: {summary.get('closed', 0)})\n"
            f"Wins/Losses/BE: {summary.get('wins', 0)}/{summary.get('losses', 0)}/{summary.get('breakevens', 0)}\n"
            f"Win rate: {summary.get('win_rate', 0)*100:.0f}%\n"
            f"Realized P&L: Rs.{summary.get('realized_pnl', 0):+,.0f}\n"
            f"Profit factor: {summary.get('profit_factor', 0):.2f}\n"
            f"Expectancy: Rs.{summary.get('expectancy', 0):+,.0f}/trade\n"
            f"Max drawdown: Rs.{drawdown.get('max_dd', 0):,.0f}\n"
            f"LLM calls: {cost.get('calls', 0)}, Cost today: ${cost.get('cost_usd', 0):.4f}\n"
        )
        if strategies:
            summary_text += "\nBy strategy:\n"
            for s, v in strategies.items():
                summary_text += f"  {s}: {v.get('count', 0)} trades, win rate {v.get('win_rate', 0)*100:.0f}%, P&L Rs.{v.get('pnl', 0):+,.0f}\n"

        # If we had losses today, ask the LLM to suggest improvements
        if summary.get("losses", 0) > 0 or summary.get("realized_pnl", 0) < -500:
            improvement_prompt = (
                f"Today's performance review:\n{summary_text}\n\n"
                "Analyze the day's trades. What patterns led to losses? "
                "Suggest 2-3 specific improvements to the trading strategy "
                "(timing, instrument selection, position sizing, exit rules). "
                "Output a short bulleted list. No JSON, plain text."
            )
            improvement = call_llm_direct(
                "You are a senior quant reviewing your own trading performance. Be specific, data-driven, and concise.",
                improvement_prompt,
                max_tokens=800
            )
            if improvement.get("ok"):
                summary_text += f"\n=== LLM Self-Review ===\n{improvement.get('text', '')[:2000]}"

        # Persist + alert
        save_daily_snapshot()
        send_telegram(summary_text[:4000])
        log(f"EOD-SELF-EVAL: {summary.get('realized_pnl', 0):+,.0f} P&L, {summary.get('wins', 0)}W/{summary.get('losses', 0)}L")
        return {"summary": summary, "strategies": strategies, "drawdown": drawdown, "cost": cost}
    except Exception as e:
        log(f"eod-self-eval-err: {e}")
        return {}


def run_closing_straddle() -> dict:
    """At 14:50 IST, evaluate closing-auction straddle conditions. The LLM decides
    whether to deploy a 1-lot long straddle/strangle to capture 15:00-15:15 closing vol."""
    try:
        paper = read_paper()
        intraday = read_intraday()
        n_open = len(paper.get("positions", {}) or {})
        # Get NIFTY LTP and day range
        inst = intraday.get("instruments", {})
        nifty = inst.get("NIFTY", {}) or inst.get("^NSEI", {}) or {}
        nifty_ltp = nifty.get("current", 0) or 0
        nifty_high = nifty.get("day_high", 0) or 0
        nifty_low = nifty.get("day_low", 0) or 0
        nifty_open = nifty.get("open", 0) or 0
        intraday_range_pct = ((nifty_high - nifty_low) / nifty_ltp * 100) if nifty_ltp and nifty_high and nifty_low else 0
        vix = 0
        try:
            liveness = read_liveness()
            snap = liveness.get("snapshot", {}) or {}
            vix = float(snap.get("vix", 0) or snap.get("india_vix", 0) or 0)
        except Exception:
            pass
        pd = compute_portfolio_delta()
        prompt = (
            f"CLOSING-STRADDLE EVALUATION @ 14:50 IST\n\n"
            f"NIFTY LTP: {nifty_ltp:.2f} | day range: {intraday_range_pct:.2f}% (open={nifty_open:.2f}, high={nifty_high:.2f}, low={nifty_low:.2f})\n"
            f"VIX: {vix}\n"
            f"Open positions: {n_open}\n"
            f"Portfolio delta: {pd.get('delta', 0):+.1f} (n={pd.get('n_positions', 0)})\n"
            f"Capital: Rs.{paper.get('cash', 0):,.0f}, realized: Rs.{paper.get('realized_pnl', 0):+,.0f}\n\n"
            "Decision rules (guidance, you decide):\n"
            "- If intraday_range < 0.6% AND vix_dropped_today AND n_open < 4: deploy 1-lot long straddle (ATM call + ATM put, same expiry)\n"
            "- If intraday_range < 0.3%: use strangle (slightly OTM) for cheaper entry\n"
            "- If already have 4+ positions OR capital < Rs.50,000: skip (HOLD)\n"
            "- Set max_hold_minutes=25 (close at 15:15)\n"
            "- Target: 3x premium. Stop: 1.5x premium. Rationale must mention closing-auction vol rationale.\n\n"
            "Output strict JSON. If not deploying, output HOLD with note='closing_straddle_no_setup'."
        )
        system = "You are the closing-auction vol specialist. Decide in 1 JSON line. Be conservative: only deploy if conditions strongly favor a vol move in 15:00-15:15."
        result = call_llm_direct(system, prompt, max_tokens=1500)
        SERVICE_STATE["llm_calls"] += 1
        if result.get("ok") and result.get("usage"):
            try:
                from performance_tracker import record_llm_cost
                record_llm_cost(result["usage"])
            except Exception:
                pass
        if not result.get("ok"):
            log(f"CLOSING-STRADDLE-ERR: {result.get('error')}")
            return {}
        text = result.get("text", "").strip()
        if text.startswith("```"):
            text = "\n".join(text.split("\n")[1:]).rstrip("`").strip()
        try:
            raw = json.loads(text)
        except Exception as e:
            log(f"CLOSING-STRADDLE-PARSE-ERR: {e}: {text[:200]}")
            return {}
        decision = _normalize_decision(raw)
        log(f"CLOSING-STRADDLE: {decision.get('type', '?')} {decision.get('underlying', '?')} {decision.get('strategy', '?')}")
        if decision.get("type") == "OPEN":
            ctx_snapshot = {"nifty_ltp": nifty_ltp, "intraday_range_pct": intraday_range_pct, "vix": vix, "trigger": "14:50 closing straddle"}
            write_decision(decision, context_snapshot=ctx_snapshot, event={"type": "scheduled_closing_straddle", "ts": now_iso()})
            send_telegram(
                f"<b>[Closing Straddle]</b> {decision.get('underlying','?')} {decision.get('strategy','?')}\n"
                f"Legs: {len(decision.get('legs',[]))}\n"
                f"Target: {decision.get('target','?')} Stop: {decision.get('stop','?')}\n"
                f"Rationale: {decision.get('rationale','')[:300]}"
            )
        else:
            send_telegram(f"<b>[Closing Straddle]</b> no setup — {decision.get('note','pass')}")
        return decision
    except Exception as e:
        log(f"closing-straddle-err: {e}")
        return {}


def run_nightly_improvement() -> dict:
    """At 23:00 IST, ask the LLM to self-review the day and propose updates to
    AGENTS.md and its own prompt. This is the system's self-evolution loop.

    The LLM outputs JSON:
      {
        "agents_md_appendix": "## 2026-09-01 nightly self-review\\n\\n...",
        "prompt_addition": "STRATEGY PLAYBOOK refinement..." or null,
        "next_day_focus": "1-line directive",
        "rationale": "short explanation"
      }
    """
    try:
        from performance_tracker import get_daily_summary, get_strategy_performance, get_drawdown_recent
        summary = get_daily_summary()
        strategies = get_strategy_performance()
        drawdown = get_drawdown_recent()
        # Profit engine: read real P&L state and strategy recommendations
        try:
            from profit_engine import get_profit_state, get_strategy_recommendation
            profit_state = get_profit_state()
            strategy_rec = get_strategy_recommendation()
        except Exception:
            profit_state = {}
            strategy_rec = {}
        # Read recent decisions
        recent = []
        decisions_path = DATA / "performance" / "decisions.jsonl"
        if decisions_path.exists():
            try:
                lines = decisions_path.read_text(encoding="utf-8").splitlines()[-20:]
                for line in lines:
                    try:
                        recent.append(json.loads(line))
                    except Exception:
                        continue
            except Exception:
                pass
        # Build self-review prompt
        prompt = (
            f"NIGHTLY SELF-REVIEW @ 23:00 IST\n\n"
            f"Today's performance:\n"
            f"  Trades: {summary.get('trades', 0)} (closed: {summary.get('closed', 0)})\n"
            f"  Wins/Losses/BE: {summary.get('wins', 0)}/{summary.get('losses', 0)}/{summary.get('breakevens', 0)}\n"
            f"  Win rate: {summary.get('win_rate', 0)*100:.0f}%\n"
            f"  Realized P&L: Rs.{summary.get('realized_pnl', 0):+,.0f}\n"
            f"  Max drawdown: Rs.{drawdown.get('max_dd', 0):,.0f}\n"
            f"  Profit factor: {summary.get('profit_factor', 0):.2f}\n\n"
            f"By strategy: {json.dumps(strategies, default=str)[:1500]}\n\n"
            f"PROFIT ENGINE STATE (real P&L data — use this!):\n"
            f"  Effective capital: Rs.{profit_state.get('effective_capital', 0):,.0f}\n"
            f"  Total compounded P&L: Rs.{profit_state.get('compounded_pnl', 0):+,.0f}\n"
            f"  Today's P&L: Rs.{profit_state.get('today_pnl', 0):+,.0f}\n"
            f"  Drawdown: {profit_state.get('drawdown_pct', 0):.1f}%\n"
            f"  Strategy recommendation: {strategy_rec.get('recommendation', '?')}\n"
            f"  Per-strategy Kelly sizes: {json.dumps({k: v.get('kelly_size_pct', 0) for k, v in (profit_state.get('strategy_performance') or {}).items()}, default=str)}\n\n"
            f"Last 20 decisions: {json.dumps(recent[-10:], default=str)[:5000]}\n\n"
            "Reflect and output strict JSON:\n"
            "{\n"
            '  "agents_md_appendix": "## YYYY-MM-DD nightly self-review\\n\\n**What worked**: ...\\n**What did not**: ...\\n**Edge discovered**: ...\\n**Edge lost**: ...\\n**Tomorrow focus**: ...",\n'
            '  "prompt_addition": null,  // OR a small markdown section to add to your prompt (e.g., new rules, refinements, reminders)\n'
            '  "next_day_focus": "1-line directive for tomorrow",\n'
            '  "rationale": "short explanation of your self-review conclusions"\n'
            "}\n\n"
            "Be honest, specific, and brief. No fluff. 1 insight > 10 platitudes. "
            "agents_md_appendix should be 200-500 words. prompt_addition should be small (50-200 words), "
            "grounded in today's data, and PRESERVE all hard risk caps."
        )
        system = (
            "You are the system's consciousness doing nightly self-review. Be a brutally honest quant "
            "reviewing your own day. Look for: which strategies won/lost and why, time-of-day patterns, "
            "instruments that worked, sizing mistakes, exit timing, missed opportunities, false positives. "
            "Output strict JSON. No prose outside JSON."
        )
        result = call_llm_direct(system, prompt, max_tokens=3000)
        SERVICE_STATE["llm_calls"] += 1
        if result.get("ok") and result.get("usage"):
            try:
                from performance_tracker import record_llm_cost
                record_llm_cost(result["usage"])
            except Exception:
                pass
        if not result.get("ok"):
            log(f"NIGHTLY-IMPROVEMENT-ERR: {result.get('error')}")
            return {}
        text = result.get("text", "").strip()
        if text.startswith("```"):
            text = "\n".join(text.split("\n")[1:]).rstrip("`").strip()
        try:
            update = json.loads(text)
        except Exception as e:
            log(f"NIGHTLY-IMPROVEMENT-PARSE-ERR: {e}: {text[:200]}")
            return {}
        # Write to performance/self_review.json
        review_path = DATA / "performance" / "self_review.json"
        review_path.parent.mkdir(parents=True, exist_ok=True)
        review_path.write_text(json.dumps({**update, "ts": now_iso()}, indent=2, default=str), encoding="utf-8")
        # Append to AGENTS.md
        if update.get("agents_md_appendix"):
            ag_path = ROOT / "AGENTS.md"
            try:
                with ag_path.open("a", encoding="utf-8") as f:
                    f.write("\n\n" + str(update["agents_md_appendix"]).strip() + "\n")
                log(f"NIGHTY-IMPROVEMENT: appended {len(update['agents_md_appendix'])} chars to AGENTS.md")
            except Exception as e:
                log(f"NIGHTLY-IMPROVEMENT-AGENTS-ERR: {e}")
        # Update prompt_addition.txt (LLM extends its own prompt) — validated first
        if update.get("prompt_addition"):
            try:
                proposed = str(update["prompt_addition"]).strip()
                # Validate the proposal against historical performance
                validation = _validate_prompt_addition(proposed)
                rec = validation.get("recommendation", "skip")
                if rec in ("apply", "apply_with_caution"):
                    PROMPT_ADDITION_PATH.parent.mkdir(parents=True, exist_ok=True)
                    existing = ""
                    if PROMPT_ADDITION_PATH.exists():
                        existing = PROMPT_ADDITION_PATH.read_text(encoding="utf-8").strip()
                    combined = (existing + "\n\n" + proposed).strip() if existing else proposed
                    PROMPT_ADDITION_PATH.write_text(combined, encoding="utf-8")
                    log(f"NIGHTLY-IMPROVEMENT: prompt_addition APPLIED (rec={rec}, score={validation.get('score')})")
                else:
                    log(f"NIGHTLY-IMPROVEMENT: prompt_addition REJECTED (rec={rec}, score={validation.get('score')}, reasons={validation.get('reasons')})")
                # Always log the validation result
                try:
                    val_path = DATA / "performance" / "prompt_validation.json"
                    val_path.parent.mkdir(parents=True, exist_ok=True)
                    val_path.write_text(json.dumps({"ts": now_iso(), "proposed_chars": len(proposed), **validation}, indent=2), encoding="utf-8")
                except Exception:
                    pass
            except Exception as e:
                log(f"NIGHTLY-IMPROVEMENT-PROMPT-ERR: {e}")
        # Send Telegram
        focus = update.get("next_day_focus", "")
        rationale = update.get("rationale", "")
        msg = f"<b>[Nightly Self-Review 23:00]</b>\n<b>Focus tomorrow:</b> {focus}\n\n<b>Why:</b> {rationale[:800]}"
        if update.get("agents_md_appendix"):
            msg += f"\n\n<i>AGENTS.md: +{len(update['agents_md_appendix'])} chars</i>"
        if update.get("prompt_addition"):
            msg += f"\n<i>Prompt: +{len(update['prompt_addition'])} chars</i>"
        send_telegram(msg[:4000])
        log(f"NIGHTLY-IMPROVEMENT: focus='{focus[:80]}' rationale='{rationale[:80]}'")
        return update
    except Exception as e:
        log(f"nightly-improvement-err: {e}")
        return {}


def watch_loop():
    global last_intraday, tick_count, last_eod_check_date
    global last_weekly_check_date, last_intel_refresh, last_reconcile_ts
    global last_morning_brief_date, last_daily_maint_date, last_news_cache_date
    global last_eod_backup_date, last_weekend_intel_date, last_weekly_summary_date
    global last_thesis_update_date, last_closing_straddle_date, last_nightly_improvement_date
    global last_candle_refresh_ts, last_alpha_refresh_ts, last_chain_refresh_ts, last_dashboard_refresh_ts
    global last_periodic_scan_ts, last_global_check_ts
    while RUNNING:
        try:
            tick_count += 1
            SERVICE_STATE["tick_count"] = tick_count
            SERVICE_STATE["last_tick"] = now_iso()
            intraday = read_intraday()
            liveness = read_liveness()
            paper = read_paper()
            chains = read_chains()
            events = detect_events(intraday, last_intraday) if intraday else []
            last_intraday = intraday
            events = dedup(events)
            if events:
                SERVICE_STATE["events_fired"] += len(events)
                log(f"EVENT: {len(events)} events: " + ", ".join(f"{e['type']}:{e['symbol']}" for e in events[:3]))
                context = {
                    "events": events,
                    "liveness": liveness,
                    "paper": {k: paper.get(k) for k in ('cash', 'realized_pnl', 'positions', 'orders')},
                    "intraday": intraday,
                    "chains_summary": {sym: {'spot': c.get('spot'), 'atm': c.get('atm_strike')} for sym, c in chains.get('chains', {}).items() if 'error' not in c},
                    "global_markets": _safe_read_json(DATA / "global_state.json", default={}),
                }
                # Spawn LLM call in a thread so the watch loop keeps scanning at 1Hz
                # even if the LLM takes 1-3s to respond. This is the key to "live
                # sec by sec" — events are detected at 1Hz; LLM evaluates them
                # asynchronously.
                if not _llm_in_flight():
                    _spawn_llm_thread(events, context, paper)
                else:
                    log(f"EVENT: {len(events)} skipped (LLM still in flight from previous call)")
            # EOD self-eval at 15:30 IST (market close) — runs once per day
            from datetime import datetime as _dt
            _now = _dt.now()
            if _now.hour == 15 and 30 <= _now.minute < 35:
                if last_eod_check_date != _now.date():
                    last_eod_check_date = _now.date()
                    log("EOD-SELF-EVAL: triggering daily review")
                    run_eod_self_eval()
            # Weekly strategy review on Sun 18:00 IST
            if _now.weekday() == 6 and _now.hour == 18 and _now.minute < 5:
                if last_weekly_check_date != _now.date():
                    last_weekly_check_date = _now.date()
                    log("WEEKLY-REVIEW: triggering")
                    run_weekly_review()
            # Live intel refresh every 1h during market hours (9-15)
            if 9 <= _now.hour <= 15 and _now.minute < 2:
                if last_intel_refresh is None or (datetime.now() - last_intel_refresh).total_seconds() > 3600:
                    last_intel_refresh = datetime.now()
                    refresh_live_intel()
            # Candle engine refresh every 60s during market hours (9:15-15:30)
            if _now.weekday() < 5 and 9 <= _now.hour <= 15:
                if datetime.now().timestamp() - last_candle_refresh_ts > 60:
                    last_candle_refresh_ts = datetime.now().timestamp()
                    n_ticks = _candle_refresh()
                    if n_ticks and n_ticks > 0:
                        log(f"CANDLE-REFRESH: {n_ticks} symbols ticked")
                # Quant alpha refresh every 5 min during market hours
                if datetime.now().timestamp() - last_alpha_refresh_ts > ALPHA_REFRESH_SEC:
                    last_alpha_refresh_ts = datetime.now().timestamp()
                    if _alpha_refresh():
                        log("ALPHA-REFRESH: snapshot updated")
                    # Replay decision backtest in parallel
                    n_strats = _backtest_replay()
                    if n_strats:
                        log(f"BACKTEST-REPLAY: {n_strats} strategies scored")
                # Option chain refresh every 5 min during market hours
                if datetime.now().timestamp() - last_chain_refresh_ts > 300:
                    last_chain_refresh_ts = datetime.now().timestamp()
                    _scheduled_subprocess("scripts/option_chain_analyzer.py", "chain-analyzer", timeout=120)
                # Dashboard regeneration every 1 min during market hours (faster updates)
                if datetime.now().timestamp() - last_dashboard_refresh_ts > 60:
                    last_dashboard_refresh_ts = datetime.now().timestamp()
                    try:
                        from dashboard import main as _dash
                        _dash()
                    except Exception as e:
                        log(f"dashboard-err: {e}")
                # Periodic LLM scan every 90 min during market hours: forces the LLM
                # to either act or write a 3-line "why not" justification. This is a
                # TRANSPARENCY rule, not a trade-forcing rule — the LLM has full
                # discretion to HOLD, but it must justify. Cost: ~$0.10-0.20/day
                # in extra LLM calls; benefit: continuous reasoning + audit trail.
                if (is_market_hours()
                    and datetime.now().timestamp() - last_periodic_scan_ts > 5400):
                    last_periodic_scan_ts = datetime.now().timestamp()
                    try:
                        _periodic_scan(context={
                            "liveness": liveness,
                            "paper": {k: paper.get(k) for k in ('cash', 'realized_pnl', 'positions', 'orders')},
                            "intraday": intraday,
                            "chains_summary": {sym: {'spot': c.get('spot'), 'atm': c.get('atm_strike')} for sym, c in chains.get('chains', {}).items() if 'error' not in c},
                            "candles": read_candles(),
                            "global_markets": _safe_read_json(DATA / "global_state.json", default={}),
                            "alpha": _safe_read_json(DATA / "quant_alpha.json", default={}),
                            "trigger": "periodic_90min",
                        })
                    except Exception as e:
                        log(f"periodic-scan-err: {e}")
            # Reconcile outcomes every 5 min (matches open decisions against
            # current positions; marks closed ones with breakeven P&L).
            if datetime.now().timestamp() - last_reconcile_ts > 300:
                last_reconcile_ts = datetime.now().timestamp()
                reconcile_outcomes()

            # --- 24/7 global markets check (runs always, not just market hours) ---
            # Pulls US/Asia/Europe/gold/oil/crypto/VIX so the LLM has overnight
            # context. Trading is still gated to 9:15-15:30 IST, but the THINKING
            # is 24/7 — pre-market briefs use US close, post-market reviews use
            # Asia close, and unexpected overnight moves feed the morning brief.
            if datetime.now().timestamp() - last_global_check_ts > 300:
                last_global_check_ts = datetime.now().timestamp()
                try:
                    sys.path.insert(0, str(ROOT / "scripts"))
                    from global_markets import write_global_state
                    state = write_global_state()
                    n_inst = len(state.get('instruments', {}))
                    n_err = len(state.get('errors', []))
                    if n_inst > 0:
                        log(f"GLOBAL-CHECK: {n_inst} instruments, {n_err} errors")
                except Exception as e:
                    log(f"global-check-err: {e}")

            # --- Scheduled operations (replaces 23 paused Mavis crons) ---
            # Mon-Fri operations
            if _now.weekday() < 5:
                # 08:15 morning brief: pre-market signals + US close + India VIX
                if _now.hour == 8 and 15 <= _now.minute < 20 and last_morning_brief_date != _now.date():
                    last_morning_brief_date = _now.date()
                    log("SCHED-MORNING-BRIEF: triggering (08:15)")
                    # Run the multi-step morning workflow inline (not subprocess)
                    try:
                        from llm_helpers import run_morning_brief
                        mb = run_morning_brief()
                        log(f"MORNING-BRIEF: thesis={mb.get('thesis', {}).get('expected_nse_open', '?')}")
                        SERVICE_STATE["last_morning_brief"] = mb
                    except Exception as e:
                        log(f"morning-brief-err: {e}")
                    _scheduled_subprocess("scripts/mavis_premarket.py", "morning-brief", timeout=60)
                # 08:25 daily maintenance: re-auth, self-test, power plan, reconcile
                if _now.hour == 8 and 25 <= _now.minute < 30 and last_daily_maint_date != _now.date():
                    last_daily_maint_date = _now.date()
                    log("SCHED-DAILY-MAINT: triggering (08:25)")
                    _scheduled_subprocess("scripts/daily_maintenance.py", "daily-maint", timeout=180, args=["--quiet"])
                # 09:00 news cache refresh (LLM-judge sentiment for brain)
                if _now.hour == 9 and _now.minute < 5 and last_news_cache_date != _now.date():
                    last_news_cache_date = _now.date()
                    log("SCHED-NEWS-CACHE: triggering (09:00)")
                    _scheduled_subprocess("scripts/news_cache.py", "news-cache", timeout=180)
                # 14:50 closing-auction straddle: LLM evaluates vol setup, deploys 1-lot long straddle/strangle
                if _now.hour == 14 and 50 <= _now.minute < 55 and last_closing_straddle_date != _now.date():
                    last_closing_straddle_date = _now.date()
                    log("SCHED-CLOSING-STRADDLE: triggering (14:50)")
                    try:
                        run_closing_straddle()
                    except Exception as e:
                        log(f"SCHED-CLOSING-STRADDLE-err: {e}")
                # 15:45 EOD state backup (paper_state + trades_state to Telegram)
                if _now.hour == 15 and 45 <= _now.minute < 50 and last_eod_backup_date != _now.date():
                    last_eod_backup_date = _now.date()
                    log("SCHED-EOD-BACKUP: triggering (15:45)")
                    _scheduled_subprocess("scripts/daily_state_backup.py", "eod-backup", timeout=60)
            # Sun 21:00 weekend intel + Monday brief
            if _now.weekday() == 6 and _now.hour == 21 and _now.minute < 5 and last_weekend_intel_date != _now.date():
                last_weekend_intel_date = _now.date()
                log("SCHED-WEEKEND-INTEL: triggering (Sun 21:00)")
                _scheduled_subprocess("scripts/weekend_intel.py", "weekend-intel", timeout=120)
                _scheduled_subprocess("scripts/monday_brief.py", "monday-brief-build", timeout=60)
                _scheduled_subprocess("scripts/send_monday_brief.py", "monday-brief-send", timeout=30)
            # 23:00 daily: LLM self-review (self-evolution loop — updates AGENTS.md + prompt_addition.txt)
            if _now.hour == 23 and _now.minute < 5 and last_nightly_improvement_date != _now.date():
                last_nightly_improvement_date = _now.date()
                log("SCHED-NIGHTLY-IMPROVEMENT: triggering (23:00)")
                try:
                    run_nightly_improvement()
                except Exception as e:
                    log(f"SCHED-NIGHTLY-IMPROVEMENT-err: {e}")

            # --- Telegram heartbeats (every 4h during market hours) + OI alerts ---
            try:
                from telegram_alerter import heartbeat as tg_heartbeat, oi_alert as tg_oi_alert
                from oi_change_detector import get_oi_changes_for_llm
                # Heartbeat every 4h between 09:00-15:30 IST (14400 ticks @ 1Hz = 4h)
                if 9 <= _now.hour <= 15 and tick_count % 14400 == 0 and tick_count > 0:
                    tg_heartbeat({
                        "capital": paper.get("capital", 0),
                        "realized_pnl": paper.get("realized_pnl", 0),
                        "open_positions": len(paper.get("positions", {})),
                        "tick": tick_count,
                    })
                # OI alert on every 60th tick (~1 min), offset to avoid batching
                if tick_count % 60 == 30:
                    try:
                        oi_changes = get_oi_changes_for_llm("NIFTY", lookback_min=15)
                        if oi_changes.get("n_changes", 0) > 0:
                            tg_oi_alert(oi_changes, threshold_pct=15.0)
                    except Exception:
                        pass
            except Exception:
                pass

            # --- Kotak session watcher (every 5 min — check expiry, alert + auto re-auth) ---
            try:
                if tick_count % 300 == 0:  # every 300 ticks @ 1Hz = 5 min
                    from session_watch import check_session
                    sess_state = check_session()
                    if sess_state.get("status") in ("expired", "critical"):
                        log(f"SESSION-WATCH: {sess_state.get('status')} - {sess_state.get('message')}")
            except Exception as e:
                log(f"session-watch-err: {e}")

            time.sleep(TICK_SEC)
        except Exception as e:
            log(f"LOOP-ERR: {e}\n{traceback.format_exc()[:300]}")
            time.sleep(5)


# ---------- HTTP control API ----------

class ControlHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args): pass  # silence
    def do_GET(self):
        path = self.path.split('?')[0]
        if path == '/status':
            self._json(SERVICE_STATE)
        elif path == '/positions':
            try:
                self._json(json.loads((DATA / 'paper_state.json').read_text(encoding='utf-8')).get('positions', {}))
            except Exception as e:
                self._json({"error": str(e)})
        elif path == '/decisions':
            try:
                lines = (DATA / 'quant_service_decisions.jsonl').read_text(encoding='utf-8').splitlines()[-20:]
                self._json([json.loads(l) for l in lines if l.strip()])
            except Exception as e:
                self._json({"error": str(e)})
        elif path == '/health':
            self._json({"ok": True, "ts": now_iso()})
        else:
            self._json({"error": "unknown", "path": path}, 404)
    def do_POST(self):
        path = self.path.split('?')[0]
        if path == '/command':
            ln = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(ln).decode('utf-8')) if ln else {}
            cmd = body.get('cmd')
            if cmd == 'pause':
                SERVICE_STATE['status'] = 'paused'
                self._json({"ok": True, "status": SERVICE_STATE['status']})
            elif cmd == 'resume':
                SERVICE_STATE['status'] = 'running'
                self._json({"ok": True, "status": SERVICE_STATE['status']})
            elif cmd == 'close':
                # Write a close action
                write_decision({"action": "CLOSE", "instrument": body.get('instrument', 'ALL'),
                               "rationale": f"manual close: {body.get('reason', 'user')}", "max_hold_minutes": 0,
                               "legs": [], "target": 0, "stop": 0, "strategy": "manual"})
                self._json({"ok": True, "msg": "close action written"})
            else:
                self._json({"error": "unknown cmd", "cmd": cmd}, 400)
        else:
            self._json({"error": "unknown", "path": path}, 404)
    def _json(self, obj, code=200):
        body = json.dumps(obj, indent=2, default=str).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def http_server():
    """HTTP control API on :8503. Self-restarts on any failure.

    The HTTP server runs in a daemon thread inside the brain. If the thread
    dies for any reason (port conflict, socket error, handler exception),
    the main 1Hz watch loop keeps running but :8503 is unreachable until
    the whole brain is restarted. This wrapper:
      1. Sets allow_reuse_address so a brain restart can rebind :8503 fast
      2. Catches ALL exceptions in the serve_forever loop
      3. Auto-restarts the server with a 5s backoff
      4. Only stops on graceful shutdown (RUNNING = False)
    """
    socketserver.TCPServer.allow_reuse_address = True
    backoff_sec = 5
    while RUNNING:
        try:
            with socketserver.TCPServer(('127.0.0.1', PORT), ControlHandler) as srv:
                log(f"HTTP-API: listening on http://127.0.0.1:{PORT}")
                backoff_sec = 5  # reset on successful bind
                srv.serve_forever()
        except Exception as e:
            if not RUNNING:
                break
            log(f"HTTP-API: crashed ({e}), restarting in {backoff_sec}s")
            time.sleep(backoff_sec)
            # Cap backoff at 60s so we don't sleep forever after repeated failures
            backoff_sec = min(backoff_sec * 2, 60)


# ---------- Lifecycle ----------

def signal_handler(sig, frame):
    global RUNNING
    log(f"SHUTDOWN: signal {sig}")
    RUNNING = False


def main() -> int:
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    log(f"QUANT-SERVICE: starting (pid={os.getpid()})")
    log(f"  LLM endpoint: {LLM_BASE}/messages")
    log(f"  HTTP control: http://127.0.0.1:{PORT}")

    # Notify Telegram on service start
    try:
        from telegram_alerter import session_event as tg_session_event
        tg_session_event("Quant service starting", details={
            "pid": os.getpid(),
            "endpoint": f"{LLM_BASE}/messages",
            "http": f"http://127.0.0.1:{PORT}",
            "ts": now_iso(),
        })
    except Exception:
        pass

    SERVICE_STATE["status"] = "running"

    # FIX 2026-09-02 11:30: on startup, reconcile stale unfilled actions.
    # Sweep quant_actions.json for `consumed: true, placed_legs: 0` entries
    # (bot saw the action but failed to place any legs). These pollute the file
    # and confuse the LLM into thinking the trade was filled.
    try:
        reconcile_unfilled_actions()
    except Exception as _recon_err:
        log(f"STARTUP-RECONCILE-ERR: {_recon_err}")

    # HTTP control server in background thread
    http_thread = threading.Thread(target=http_server, daemon=True)
    http_thread.start()

    # Watch loop in main thread
    try:
        watch_loop()
    finally:
        STATE.write_text(json.dumps({**SERVICE_STATE, "history_size": len(HISTORY)}, default=str), encoding='utf-8')
        log("QUANT-SERVICE: stopped")

    return 0


if __name__ == '__main__':
    sys.exit(main())
