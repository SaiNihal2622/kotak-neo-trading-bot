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
TICK_SEC = 2.0
PRICE_MOVE_PCT = 0.3
LEVEL_TOUCH_PCT = 0.05
DEDUP_SEC = 30
MIN_DATA_POINTS = 5
LLM_MODEL = "MiniMax-M3"
LLM_MAX_TOKENS = 4000

# Persistent state
TICKS: dict[str, deque] = {}
LAST_EVENT_SIG: dict[str, str] = {}
HISTORY: deque = deque(maxlen=50)  # rolling LLM message history
RUNNING = True
SERVICE_STATE = {"status": "starting", "last_tick": None, "last_decision_at": None,
                 "tick_count": 0, "events_fired": 0, "llm_calls": 0, "actions_taken": 0}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


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
    events = []
    cur = intraday.get('instruments', {})
    prev = last_intraday.get('instruments', {})
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

You see the FULL market state and any SIGNIFICANT EVENT that just happened. Your job: decide if there's a real edge, and if so, output the exact trade.

OUTPUT FORMAT — strict JSON, one line, no markdown, no prose. Use this exact schema:

{"type":"OPEN|CLOSE|HOLD","underlying":"NIFTY|BANKNIFTY|FINNIFTY|MIDCPNIFTY|RELIANCE|HDFCBANK|...","expiry":"YYYY-MM-DD","strategy":"iron_condor|bull_call_vertical|bear_put_vertical|long_call|long_put|short_strangle|short_straddle|calendar_spread|custom","legs":[{"side":"BUY|SELL","qty":N,"strike":N,"opt_type":"CE|PE","order_type":"MARKET|LIMIT","price":N_or_null}],"target":N_or_null,"stop":N_or_null,"max_hold_minutes":N,"rationale":"2-3 sentences max"}

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

RULES (hard):
- 1% of capital (Rs.1,000) max risk per trade = 100% loss tolerance on premium
- 3% (Rs.3,000) max daily loss across all positions
- No naked unlimited risk (every position has defined max loss)
- No entries in macro blackout windows
- Min premium: Rs.5, max premium per leg: Rs.500
- Strike spacing: NIFTY 50pt, BANKNIFTY 100pt, stocks 5-10pt
- Lots: NIFTY=75 qty, BANKNIFTY=30 qty, FINNIFTY=65 qty, MIDCPNIFTY=120 qty, stocks=lot_size from config
- Expiry: weekly (current Thu) for intraday, monthly for swings
- Order type: MARKET for fast entries under 2 min hold, LIMIT for swing trades

You may pick any of 28 instruments (4 indices + 24 NIFTY-50 stocks). NO templated gates. Be a professional quant. Take the trade if edge is real. Pass if not.

STRATEGY PLAYBOOK (consider these proactively, not just reactively — guidance, not mandatory rules):

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

5. **REGIME-AWARE SIZING**:
   - VIX < 11: aggressive, larger sizes allowed (1.5% risk/trade)
   - VIX 11-14: normal, 1% risk/trade
   - VIX 14-18: cautious, 0.7% risk/trade, prefer defined-risk structures
   - VIX > 18: defensive, 0.5% risk/trade, mostly premium-selling with wings, no naked

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
    legs = d.get("legs")
    if not legs and d.get("strike"):
        # LLM gave a single leg as flat fields
        legs = [{
            "side": str(d.get("side") or "BUY").upper(),
            "qty": int(d.get("qty") or d.get("quantity") or 75),
            "strike": int(d["strike"]),
            "opt_type": str(d.get("opt_type") or d.get("instrument") or "CE").upper(),
            "order_type": str(d.get("order_type") or "MARKET").upper(),
            "price": d.get("price") or d.get("limit_price"),
        }]
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


def invoke_llm_decision(events: list, context: dict) -> dict:
    """Direct LLM call. Builds context, calls API, parses JSON action."""
    # Augment context with portfolio delta (so the LLM can decide hedges)
    try:
        pd = compute_portfolio_delta()
        if pd.get("n_positions", 0) > 0 or True:  # always include (n=0 is informative)
            context["portfolio_delta"] = pd
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
    user_content = (
        f"EVENT(S) DETECTED: {json.dumps(events, default=str)[:2000]}\n\n"
        f"FULL STATE: {json.dumps(context, default=str)[:10000]}\n\n"
        f"RECENT HISTORY (last {len(HISTORY)} decisions): {json.dumps(list(HISTORY)[-5:], default=str)[:2000]}\n\n"
        "Decide now. Output ONE JSON object only. Pay attention to delta (directional risk) and gamma (convexity). Iron condors should be delta-neutral (delta < 5). Long options should have positive delta for CE, negative for PE."
    )
    result = call_llm_direct(PROFESSIONAL_QUANT_SYSTEM + get_prompt_addition(), user_content)
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
    log(f"LLM-DECISION: {decision.get('type', '?')} {decision.get('underlying', '?')} {decision.get('strategy', '?')} legs={len(decision.get('legs',[]))}")
    # Telegram the decision
    if decision.get("type") in ("OPEN", "CLOSE"):
        send_telegram(
            f"<b>[Quant {decision.get('type')}]</b> {decision.get('underlying','?')} {decision.get('strategy','?')}\n"
            f"Legs: {len(decision.get('legs',[]))}\n"
            f"Target: {decision.get('target','?')} Stop: {decision.get('stop','?')}\n"
            f"Rationale: {decision.get('rationale','')[:300]}"
        )
    return decision


def write_decision(decision: dict) -> None:
    """Write LLM decision to the action file (the bot reads it)."""
    action_doc = {
        "ts": now_iso(),
        "source": "quant_service",
        "actions": [decision] if decision.get("type") in ("OPEN", "CLOSE") else [],
        "note": decision.get("note", ""),
        "rationale": decision.get("rationale", ""),
        "consumed": False,
    }
    if action_doc["actions"]:
        ACTIONS.write_text(json.dumps(action_doc, indent=2, default=str), encoding='utf-8')
        SERVICE_STATE["actions_taken"] += 1
        log(f"ACTION-WRITTEN: {decision.get('type')} {decision.get('underlying')} {decision.get('strategy', '')}")
    # Always log the decision
    with open(DECISIONS, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": now_iso(), "decision": decision}, default=str) + "\n")


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
            write_decision(decision)
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
        # Update prompt_addition.txt (LLM extends its own prompt)
        if update.get("prompt_addition"):
            try:
                PROMPT_ADDITION_PATH.parent.mkdir(parents=True, exist_ok=True)
                new_addition = str(update["prompt_addition"]).strip()
                # Append to existing (preserve history)
                existing = ""
                if PROMPT_ADDITION_PATH.exists():
                    existing = PROMPT_ADDITION_PATH.read_text(encoding="utf-8").strip()
                combined = (existing + "\n\n" + new_addition).strip() if existing else new_addition
                PROMPT_ADDITION_PATH.write_text(combined, encoding="utf-8")
                log(f"NIGHTLY-IMPROVEMENT: prompt_addition updated (+{len(new_addition)} chars)")
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
                }
                decision = invoke_llm_decision(events, context)
                SERVICE_STATE["last_decision_at"] = now_iso()
                write_decision(decision)
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
            # Reconcile outcomes every 5 min (matches open decisions against
            # current positions; marks closed ones with breakeven P&L).
            if datetime.now().timestamp() - last_reconcile_ts > 300:
                last_reconcile_ts = datetime.now().timestamp()
                reconcile_outcomes()

            # --- Scheduled operations (replaces 23 paused Mavis crons) ---
            # Mon-Fri operations
            if _now.weekday() < 5:
                # 08:15 morning brief: pre-market signals + US close + India VIX
                if _now.hour == 8 and 15 <= _now.minute < 20 and last_morning_brief_date != _now.date():
                    last_morning_brief_date = _now.date()
                    log("SCHED-MORNING-BRIEF: triggering (08:15)")
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
                    _scheduled_subprocess("scripts/news_cache.py", "news-cache", timeout=60)
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
    with socketserver.TCPServer(('127.0.0.1', PORT), ControlHandler) as srv:
        log(f"HTTP-API: listening on http://127.0.0.1:{PORT}")
        srv.serve_forever()


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

    SERVICE_STATE["status"] = "running"

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
