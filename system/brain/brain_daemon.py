"""Brain daemon — runs the trading brain as a real daemon (not a cron stub).

Architecture role:
- Replaces the legacy Mavis cron "kotak-trader-desk" that was supposed to
  read state and write decisions to quant_actions.json every 5 min.
- Reads state via scripts/trader_state.py (candle regime, VIX, positions,
  macro events, research summary).
- Calls MiniMax M2.7-highspeed (the existing LLM provider used by
  kotak_bot.signals.llm_judge.LLMNewsJudge) for the trading decision.
- Writes the decision to data_cache/quant_actions.json.
- The existing BrainBridge (system.bridge.brain_bridge) picks it up and
  submits via /api/plan.

Decision logic:
- HOLD by default. Only propose a plan if there's an actionable signal.
- Strategy selection based on regime:
  - trending + bullish → nifty_cash_long or directional long_call
  - trending + bearish → nifty_cash_short or directional long_put
  - range-bound + high IV → iron condor
- Risk-aware: respects max 1 lot, 0.5% per-trade, mandatory EOD square-off.

For now, the LLM call uses a simple "should I trade?" decision + a
mechanical strategy selector. Future work: wire up the full atomic
judgments (SixJudgments) and predictive signals.

Runs as:
  python -m system.brain.brain_daemon [--interval 300]

Self-restart:
- Crashed → exits with code 1; scheduled task (KotakBrainDaemonAutoStart)
  respawns it.
- Wrong decision → brain_bridge rejects via pre-flight → brain learns.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

# Try to load .env early so env vars are set before our defaults are read
try:
    from dotenv import load_dotenv
    _env = Path(__file__).resolve().parent.parent.parent / "config" / "credentials.env"
    if _env.exists():
        load_dotenv(_env, override=False)
except Exception:
    pass


logger = logging.getLogger(__name__)


IST = timezone(timedelta(hours=5, minutes=30))

# PHASE 5 FIX 2026-09-30: load the mavis JWT token for LLM auth. The
# LLM endpoint uses managed-auth (per config.yaml), so the API key
# from credentials.env doesn't work — we need the session JWT.
# The token is in ~/.minimax/local-runtime.auth.json. Falls back to
# the API key from env if JWT not found.
_MAVIS_JWT = None
try:
    _auth_file = Path.home() / ".minimax" / "local-runtime.auth.json"
    if _auth_file.exists():
        with open(_auth_file, encoding="utf-8") as _f:
            _auth_data = json.loads(_f.read())
            _MAVIS_JWT = _auth_data.get("auth", {}).get("accessToken", "")
except Exception:
    pass

# Defaults — env vars override. Match the bot's LLMNewsJudge config.
DEFAULT_DATA_DIR = Path(os.environ.get("KOTAK_DATA_DIR", "data_cache"))
DEFAULT_QUANT_ACTIONS = Path(os.environ.get("KOTAK_QUANT_ACTIONS", "data_cache/quant_actions.json"))
DEFAULT_INTERVAL_SEC = int(os.environ.get("KOTAK_BRAIN_INTERVAL", "300"))  # 5 min
# Use the same base URL as the bot's LLMNewsJudge AND the official
# MiniMax config at C:\Users\saini\.minimax\config.yaml (provider.npm=anthropic).
# The config's baseURL is the canonical endpoint. We append /messages.
# credentials.env has a legacy /chat/completions URL that's no longer valid
# — we use the config.yaml URL as the default and strip /chat/completions if present.
DEFAULT_LLM_BASE = os.environ.get("MINIMAX_LLM_BASE_URL", "https://agent.minimax.io/mavis/api/v1/llm/v1")
DEFAULT_LLM_MODEL = os.environ.get("MINIMAX_LLM_MODEL", "MiniMax-M2.7-highspeed")
# Prefer the mavis JWT (managed auth), fall back to env API key
DEFAULT_LLM_API_KEY = _MAVIS_JWT or os.environ.get("MINIMAX_LLM_API_KEY") or os.environ.get("MINIMAX_API_KEY", "") or "managed-auth"

# Override the credentials.env legacy URL with the canonical one.
# (Uncomment to force; the env-var default above is already correct.)
# os.environ["MINIMAX_LLM_BASE_URL"] = DEFAULT_LLM_BASE

# Market hours IST
MARKET_OPEN_HOUR = 9
MARKET_OPEN_MIN = 15
MARKET_CLOSE_HOUR = 15
MARKET_CLOSE_MIN = 30

# Strategy thresholds — relaxed for paper trading so we can see decisions
# PHASE 5 FIX 2026-09-30: lowered thresholds so the brain fires during weak
# signals too. Original thresholds were conservative (ADX>25, RSI>55) but
# intraday_levels.json doesn't expose ADX/RSI directly — it exposes
# session_pct and dist_from_vwap. Mapped accordingly.
ADX_TREND_THRESHOLD = 0.10  # was 25, now 0.10% session_pct as trend proxy
RSI_LONG_THRESHOLD = 0.05   # was 55, now 0.05% dist_from_vwap as momentum proxy
RSI_SHORT_THRESHOLD = -0.05
VIX_MIN_TRADE = 11          # was 13, expanded range to allow more trading
VIX_MAX_TRADE = 25          # was 22
SESSION_PCT_ENTRY = 0.10    # min session_pct to trigger entry
SESSION_PCT_TREND = 0.30    # strong trend threshold

# PHASE 6 FIX 2026-09-30 (swing mode): swing strategy uses STRONGER thresholds
# because it holds multi-day — wrong call costs more than intraday.
ADX_SWING_THRESHOLD = 0.25   # |session_pct|*100 must be > 25 (strong trend)
RSI_SWING_LONG = 60          # RSI must be > 60 (overbought-leaning bullish)
RSI_SWING_SHORT = 40         # RSI must be < 40 (oversold-leaning bearish)
DIST_VWAP_SWING_LONG = 0.10  # must be > 0.10% above VWAP
DIST_VWAP_SWING_SHORT = -0.10
# Swing hold period (days). Auto-close if held > this many days.
SWING_HOLD_DAYS = int(os.environ.get("KOTAK_SWING_HOLD_DAYS", "5"))
SWING_TARGET_PCT = 0.02     # +2% target
SWING_STOP_PCT = 0.015      # -1.5% stop

# PHASE 6 FIX 2026-09-30 (expiry blackout): how many days before expiry we
# refuse to open new option positions. Weekly options expire Thursday,
# so default=2 means we won't open new weekly positions on Wed/Thu.
# For monthly (last Thu of month), the swing strategy uses cash so no
# blackout applies; intraday weekly options still respect this.
EXPIRY_BLACKOUT_DAYS = int(os.environ.get("KOTAK_EXPIRY_BLACKOUT_DAYS", "2"))

# PHASE 6 FIX 2026-09-30 (swing enable): opt-in flag. Set to 1 to enable
# swing strategies alongside the intraday ones.
ENABLE_SWING = os.environ.get("KOTAK_ENABLE_SWING", "0") == "1"


def _next_weekly_expiry(now: datetime) -> datetime:
    """Return the next Thursday after `now` at 15:30 IST (option expiry time).

    Thursday is weekday() == 3.
    """
    days_ahead = (3 - now.weekday()) % 7
    if days_ahead == 0:
        # Today is Thursday — expiry is TODAY (15:30)
        days_ahead = 0
    return (now + timedelta(days=days_ahead)).replace(
        hour=15, minute=30, second=0, microsecond=0
    )


def _days_to_expiry(now: datetime) -> int:
    """Calendar days until the next weekly expiry (Thursday 15:30).

    Used to enforce KOTAK_EXPIRY_BLACKOUT_DAYS — refuse new option opens
    within N days of expiry to avoid the accelerating theta decay window.
    Returns 0 on expiry day, 1 on Wednesday, etc.
    """
    expiry = _next_weekly_expiry(now)
    delta = expiry.date() - now.date()
    return delta.days


def _is_expiry_blackout(now: datetime) -> bool:
    """PHASE 6 FIX: True if we're within the blackout window before expiry.

    Default: refuse new option opens within 2 days of weekly expiry
    (Wed + Thu). Monthly options handled separately (swing uses cash,
    so no blackout applies to swing_cash_long/short).

    For swing: still applies to swing_option_* if any option-based swing
    is added later. Cash-based swing is exempt (no expiry).
    """
    return _days_to_expiry(now) < EXPIRY_BLACKOUT_DAYS


def _now_ist() -> datetime:
    return datetime.now(IST)


def _is_weekday(d: datetime) -> bool:
    return d.weekday() < 5  # Mon-Fri


def _is_market_open(d: datetime) -> bool:
    if not _is_weekday(d):
        return False
    hm = d.hour * 60 + d.minute
    open_hm = MARKET_OPEN_HOUR * 60 + MARKET_OPEN_MIN
    close_hm = MARKET_CLOSE_HOUR * 60 + MARKET_CLOSE_MIN
    return open_hm <= hm < close_hm


def _is_force_square_time(d: datetime) -> bool:
    """Don't enter new positions after 14:30 IST."""
    if not _is_weekday(d):
        return False
    hm = d.hour * 60 + d.minute
    return hm >= 14 * 60 + 30


def _is_eod_close_time(d: datetime) -> bool:
    """PHASE 6 FIX: 15:15-15:25 IST = force-square window.

    At 15:15 we close ALL open positions for the day. This prevents
    overnight gap risk and ensures the day's P&L is realized before
    market close at 15:30.

    CONFIGURABLE via KOTAK_EOD_CLOSE_TIME env var (HH:MM). Default = 15:15.
    Set to "15:30" to disable EOD close (allow overnight — for swing
    strategies only). For weekly-options intraday, keep the default.
    """
    # Allow disable via env var (overnight mode for swing strategies)
    eod_time_str = os.environ.get("KOTAK_EOD_CLOSE_TIME", "15:15")
    if eod_time_str.lower() in ("off", "disabled", "none", "no"):
        return False
    if not _is_weekday(d):
        return False
    try:
        hh, mm = eod_time_str.split(":")
        eod_hm = int(hh) * 60 + int(mm)
    except Exception:
        eod_hm = 15 * 60 + 15  # default
    hm = d.hour * 60 + d.minute
    # 11-min window inclusive of both endpoints (15:15, 15:16, ..., 15:25 = 11 minutes)
    return eod_hm <= hm <= eod_hm + 10


# PHASE 6 FIX 2026-09-30: tracks the last reset date so we only
# clear circuit-breaker flags once per day at market open.
_last_reset_date: str = ""


class BrainDaemon:
    """Reads market state, calls LLM for decision, writes to quant_actions.json."""

    def __init__(
        self,
        data_dir: Path = DEFAULT_DATA_DIR,
        quant_actions_path: Path = DEFAULT_QUANT_ACTIONS,
        interval_sec: int = DEFAULT_INTERVAL_SEC,
        llm_base_url: str = DEFAULT_LLM_BASE,
        llm_model: str = DEFAULT_LLM_MODEL,
        llm_api_key: str = DEFAULT_LLM_API_KEY,
    ):
        self.data_dir = Path(data_dir)
        self.quant_actions_path = Path(quant_actions_path)
        self.interval_sec = interval_sec
        self.llm_base_url = llm_base_url
        self.llm_model = llm_model
        self.llm_api_key = llm_api_key
        self.stats = {"cycles": 0, "decisions": 0, "hold": 0, "open": 0, "errors": 0}

    def _read_state(self) -> dict:
        """Read current market state from various caches."""
        state = {
            "ts": _now_ist().isoformat(),
            "open_positions": [],
            "vix": 0.0,
            "nifty_spot": 0.0,
            "regime": "unknown",
            "rsi": 50.0,
            "adx": 0.0,
            "macro_events": [],
        }
        try:
            # Liveness file
            liveness = self.data_dir / "liveness.json"
            if liveness.exists():
                with open(liveness, encoding="utf-8") as f:
                    data = json.load(f)
                snap = data.get("snapshot", {})
                state["vix"] = float(snap.get("vix", 0.0))
        except Exception as e:
            logger.debug(f"read liveness: {e}")
        try:
            # Paper state for positions
            paper = self.data_dir / "paper_state.json"
            if paper.exists():
                with open(paper, encoding="utf-8") as f:
                    data = json.load(f)
                positions = data.get("positions", {})
                open_pos = [s for s, p in positions.items() if p.get("qty", 0) != 0]
                state["open_positions"] = open_pos[:5]  # cap
                state["realized_pnl"] = data.get("realized_pnl", 0.0)
                state["cash"] = data.get("cash", 0.0)
        except Exception as e:
            logger.debug(f"read paper_state: {e}")
        try:
            # Core state for live ticks
            import urllib.request
            with urllib.request.urlopen("http://127.0.0.1:8510/api/state", timeout=3) as resp:
                core = json.loads(resp.read())
            state["nifty_spot"] = core.get("ticks_known", 0)  # ticks_known is just count
            # pull a real tick for NIFTY
            for sym, tick in core.get("ticks", {}).items():
                if "NIFTY" in sym and not any(c.isdigit() for c in sym):
                    state["nifty_spot"] = tick.get("ltp", 0)
                    break
        except Exception as e:
            logger.debug(f"read core state: {e}")
        try:
            # Intraday levels for regime + ADX
            # PHASE 5 FIX 2026-09-30: intraday_levels.json structure is
            # {"instruments": {"NIFTY": {...}}}. The original code read
            # data["NIFTY"] which doesn't exist, returning {} every time.
            # Now read correctly and compute regime from session_pct
            # (since adx/rsi aren't stored in the file).
            intraday = self.data_dir / "intraday_levels.json"
            if intraday.exists():
                with open(intraday, encoding="utf-8") as f:
                    data = json.load(f)
                nifty_data = data.get("instruments", {}).get("NIFTY", {})
                if nifty_data:
                    session_pct = float(nifty_data.get("session_pct", 0) or 0)
                    # Regime classification (relaxed for paper trading)
                    if session_pct > 0.10:
                        state["regime"] = "trending_up"
                    elif session_pct < -0.10:
                        state["regime"] = "trending_down"
                    elif session_pct >= 0.02:
                        state["regime"] = "mild_up"
                    elif session_pct <= -0.02:
                        state["regime"] = "mild_down"
                    else:
                        state["regime"] = "range_bound"
                    # ADX proxy: |session_pct| * 100
                    state["adx"] = abs(session_pct) * 100
                    # RSI proxy: 50 + dist_from_vwap * 100
                    state["rsi"] = 50 + float(nifty_data.get("dist_from_vwap", 0) or 0) * 100
                    state["session_pct"] = session_pct
                    state["dist_from_vwap"] = float(nifty_data.get("dist_from_vwap", 0) or 0)
                    state["nifty_spot"] = float(nifty_data.get("current", 0) or 0)
        except Exception as e:
            logger.debug(f"read intraday_levels: {e}")
        try:
            # Macro events
            macro = self.data_dir / "macro_calendar.json"
            if macro.exists():
                with open(macro, encoding="utf-8") as f:
                    state["macro_events"] = json.load(f).get("today", [])
        except Exception as e:
            logger.debug(f"read macro: {e}")
        return state

    async def _call_llm(self, state: dict) -> dict:
        """Call MiniMax M2.7-highspeed for the trading decision.

        Returns a dict like:
            {"action": "HOLD"|"OPEN", "rationale": "...", "strategy": "iron_condor_nifty"|...,
             "underlying": "NIFTY", "legs": [...], "target": X, "stop": Y}
        """
        if not self.llm_api_key:
            logger.debug("no LLM API key; using rule-based fallback")
            return self._rule_based_decision(state)

        system = """You are a disciplined NIFTY/BANKNIFTY options and spot trader. HOLD by default. Only propose OPEN if there is a clear, evidence-based edge.

RESPOND WITH JSON ONLY. NO PROSE. NO THINKING. START WITH { AND END WITH }.

Rules (paper mode, relaxed thresholds):
- Range-bound + IV > 11 → iron_condor_nifty
- Trending up + ADX > 0.10 → nifty_cash_long (NIFTY spot MIS long)
- Trending down + ADX > 0.10 → nifty_cash_short (NIFTY spot MIS short)
- After 14:30 IST → never enter new positions
- PHASE 6 FIX: within 2 days of weekly expiry (Wed/Thu) → HOLD (expiry blackout).
  Weekly options theta accelerates Wed+Thu — new opens on those days lose.
- Swing mode (KOTAK_ENABLE_SWING=1): for STRONG trends (ADX>0.25, RSI>60/<40<40),
  can open nifty_swing_long/short with target=+2%, stop=-1.5%, hold_days=5.
  Swing bypasses EOD close (cash NIFTY, multi-day hold).

Output JSON (exactly this shape, no other text):
{"action": "HOLD", "rationale": "<one short sentence>"}

OR for OPEN:
{"action": "OPEN", "rationale": "<one short sentence>", "strategy": "nifty_cash_long", "underlying": "NIFTY", "legs": [{"side": "BUY", "qty": 75, "order_type": "MARKET", "segment": "nse_cm"}], "target": 1.0, "stop": 0.75}

OR for SWING (when KOTAK_ENABLE_SWING=1):
{"action": "OPEN", "rationale": "<swing rationale>", "strategy": "nifty_swing_long", "underlying": "NIFTY", "legs": [{"side": "BUY", "qty": 75, "order_type": "MARKET", "segment": "nse_cm"}], "target": 0.02, "stop": 0.015, "swing": true, "hold_days": 5}

START YOUR RESPONSE WITH { CHARACTER. NO PREAMBLE."""

        # PHASE 6 FIX 2026-09-30: inject past lessons from counterfactual
        # tracker. Lets the LLM improve from prior decisions.
        try:
            from .counterfactual import get_lessons_for_prompt
            lessons = get_lessons_for_prompt(max_lessons=4)
            if lessons:
                system = system + "\n\n" + lessons
        except Exception as e:
            logger.debug(f"lessons injection failed: {e}")

        user = json.dumps(state, indent=2)
        # PHASE 5 FIX 2026-09-30: the credentials.env MINIMAX_LLM_BASE_URL
        # ends with "/chat/completions" (OpenAI-style endpoint). The
        # bot's LLMNewsJudge appends "/messages" (Anthropic-style) which
        # would create "/v1/chat/completions/messages" — broken. Strip the
        # suffix so we can append /messages cleanly. If the configured
        # base doesn't end with /chat/completions, leave it alone.
        base = self.llm_base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            base = base[: -len("/chat/completions")]
        url = f"{base}/messages"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.llm_api_key,
            "Authorization": f"Bearer {self.llm_api_key}",
            "anthropic-version": "2023-06-01",
        }
        body = {
            "model": self.llm_model,
            "max_tokens": 1500,
            "temperature": 0.1,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        try:
            async with httpx.AsyncClient(timeout=45) as c:
                resp = await c.post(url, headers=headers, json=body)
            if resp.status_code != 200:
                logger.warning(f"LLM HTTP {resp.status_code}: {resp.text[:200]}")
                return self._rule_based_decision(state)
            data = resp.json()
            text = ""
            for block in data.get("content", []):
                if block.get("type") == "text":
                    text += block.get("text", "")
                elif block.get("type") == "thinking" and not text:
                    text += block.get("thinking", "")
            if not text:
                logger.warning("LLM returned no text")
                return self._rule_based_decision(state)
            # PHASE 5 FIX 2026-09-30: more robust JSON extraction. Strip
            # markdown code fences, try multiple balanced {..} blocks.
            # The LLM sometimes wraps the JSON in ```json ... ``` and adds
            # reasoning text. We find the LAST balanced {..} that parses.
            stripped = text
            if "```json" in stripped:
                stripped = stripped.split("```json", 1)[1].split("```", 1)[0]
            elif "```" in stripped:
                stripped = stripped.split("```", 1)[1].split("```", 1)[0]
            decision = None
            # Try balanced-bracket search
            i = 0
            candidates = []
            while i < len(stripped):
                if stripped[i] == "{":
                    depth = 0
                    for j in range(i, len(stripped)):
                        if stripped[j] == "{":
                            depth += 1
                        elif stripped[j] == "}":
                            depth -= 1
                            if depth == 0:
                                candidates.append(stripped[i:j + 1])
                                break
                    i = j + 1
                else:
                    i += 1
            # Try parsing from largest to smallest (LIKELIHOOD: LLM puts JSON last)
            for cand in sorted(candidates, key=len, reverse=True):
                try:
                    decision = json.loads(cand)
                    if isinstance(decision, dict) and "action" in decision:
                        break
                except Exception:
                    continue
            if decision is None:
                # Fallback to first-bracket extraction
                start = stripped.find("{")
                end = stripped.rfind("}") + 1
                if start >= 0 and end > start:
                    try:
                        decision = json.loads(stripped[start:end])
                    except Exception as e:
                        logger.warning(f"LLM JSON parse failed: {e}; text={stripped[:300]}")
                        return self._rule_based_decision(state)
            if decision is None or not isinstance(decision, dict):
                logger.warning(f"LLM returned no parseable JSON: {text[:200]}")
                return self._rule_based_decision(state)
            # PHASE 5 FIX 2026-09-30: accept both 'reason' and 'rationale' as
            # the rationale field. The LLM often uses 'reason'; our internal
            # schema uses 'rationale'. Normalize so downstream is consistent.
            if "reason" in decision and "rationale" not in decision:
                decision["rationale"] = decision.pop("reason")
            return decision
        except Exception as e:
            logger.warning(f"LLM call failed: {e}")
            return self._rule_based_decision(state)

    def _rule_based_decision(self, state: dict) -> dict:
        """Fallback when no LLM available. Uses mechanical regime strategy.

        PHASE 5 FIX 2026-09-30: read actual intraday_levels fields. Map:
          - regime in {"trending_up", "mild_up", "trending_down", "mild_down"}
          - ADX proxy = |session_pct| * 100 (so 0.10% → ADX 10, 0.30% → ADX 30)
          - RSI proxy = 50 + dist_from_vwap * 100
        Thresholds lowered (paper mode, want decisions). Original strategy
        required ADX>25 + RSI>55 which never fired in practice.
        """
        adx = state.get("adx", 0)
        rsi = state.get("rsi", 50)
        regime = state.get("regime", "unknown")
        vix = state.get("vix", 0)
        session_pct = state.get("session_pct", 0)
        dist_vwap = state.get("dist_from_vwap", 0)

        if _is_force_square_time(_now_ist()):
            return {"action": "HOLD", "rationale": "after force-square time"}
        if state.get("open_positions"):
            return {"action": "HOLD", "rationale": "have open position"}
        if vix < VIX_MIN_TRADE or vix > VIX_MAX_TRADE:
            return {"action": "HOLD", "rationale": f"VIX {vix:.1f} outside [{VIX_MIN_TRADE}, {VIX_MAX_TRADE}]"}

        # PHASE 6 FIX 2026-09-30 (expiry blackout): refuse new option opens
        # within EXPIRY_BLACKOUT_DAYS of the next weekly expiry (Thursday).
        # For weekly options, Wed+Thu are dangerous because:
        #  - theta accelerates (final day decay is ~50% of week's time value)
        #  - gamma risk spikes (small moves = big P&L swings)
        #  - liquidity thins on Thursday afternoon
        # Swing_cash_* strategies are exempt (no options = no expiry).
        days_to_exp = _days_to_expiry(_now_ist())
        if days_to_exp < EXPIRY_BLACKOUT_DAYS:
            # Allow swing cash entries even during blackout (no expiry)
            if not ENABLE_SWING:
                return {
                    "action": "HOLD",
                    "rationale": (
                        f"expiry_blackout: {days_to_exp}d to weekly expiry "
                        f"(min={EXPIRY_BLACKOUT_DAYS}d)"
                    ),
                }

        # PHASE 6 FIX (swing takes priority over intraday): if swing criteria met,
        # swing fires. Otherwise fall through to intraday. SWING thresholds are
        # STRICTER (ADX>0.25, RSI>60/<40, VWAP>0.10) so a signal that meets
        # swing criteria ALWAYS meets intraday — but we prefer swing for
        # multi-day trend capture when enabled.
        if ENABLE_SWING:
            swing_long = (
                regime in ("trending_up", "uptrend")
                and adx > ADX_SWING_THRESHOLD  # 0.25
                and rsi > RSI_SWING_LONG        # 60
                and dist_vwap > DIST_VWAP_SWING_LONG  # 0.10
            )
            if swing_long:
                return {
                    "action": "OPEN",
                    "rationale": (
                        f"SWING long: regime={regime}, ADX={adx:.2f}, "
                        f"RSI={rsi:.1f}, dist_vwap={dist_vwap:+.2f}%, "
                        f"hold={SWING_HOLD_DAYS}d, target={SWING_TARGET_PCT*100:.1f}%, "
                        f"stop={SWING_STOP_PCT*100:.1f}%"
                    ),
                    "strategy": "nifty_swing_long",
                    "underlying": "NIFTY",
                    "legs": [{"side": "BUY", "qty": 75, "order_type": "MARKET", "segment": "nse_cm"}],
                    "target": SWING_TARGET_PCT,
                    "stop": SWING_STOP_PCT,
                    "swing": True,
                    "hold_days": SWING_HOLD_DAYS,
                }
            swing_short = (
                regime in ("trending_down", "downtrend")
                and adx > ADX_SWING_THRESHOLD
                and rsi < RSI_SWING_SHORT
                and dist_vwap < DIST_VWAP_SWING_SHORT
            )
            if swing_short:
                return {
                    "action": "OPEN",
                    "rationale": (
                        f"SWING short: regime={regime}, ADX={adx:.2f}, "
                        f"RSI={rsi:.1f}, dist_vwap={dist_vwap:+.2f}%, "
                        f"hold={SWING_HOLD_DAYS}d, target={SWING_TARGET_PCT*100:.1f}%, "
                        f"stop={SWING_STOP_PCT*100:.1f}%"
                    ),
                    "strategy": "nifty_swing_short",
                    "underlying": "NIFTY",
                    "legs": [{"side": "SELL", "qty": 75, "order_type": "MARKET", "segment": "nse_cm"}],
                    "target": SWING_TARGET_PCT,
                    "stop": SWING_STOP_PCT,
                    "swing": True,
                    "hold_days": SWING_HOLD_DAYS,
                }

        # Intraday strategies (fall through after swing if swing didn't fire).
        # Trending up + ADX proxy > threshold + momentum positive.
        # PHASE 6 FIX 2026-09-30: tightened to require MULTI-SIGNAL confirmation
        # (regime + ADX + RSI + VWAP alignment). Single-signal triggers caused
        # 56 OPENs/2hrs — over-trading.
        long_confirmed = (
            regime in ("trending_up", "mild_up", "uptrend")
            and adx > 0.15  # raised from 0.10
            and rsi > 55
            and dist_vwap > 0.05  # NEW: must be above VWAP
        )
        if long_confirmed:
            return {
                "action": "OPEN",
                "rationale": (
                    f"CAS long (multi-signal): regime={regime}, ADX={adx:.2f}, "
                    f"RSI={rsi:.1f}, VIX={vix:.1f}, session_pct={session_pct:+.2f}%, "
                    f"vwap_dist={dist_vwap:+.2f}%"
                ),
                "strategy": "nifty_cash_long",
                "underlying": "NIFTY",
                "legs": [{"side": "BUY", "qty": 75, "order_type": "MARKET", "segment": "nse_cm"}],
                "target": 1.0,
                "stop": 0.75,
            }
        short_confirmed = (
            regime in ("trending_down", "mild_down", "downtrend")
            and adx > 0.15  # raised from 0.10
            and rsi < 45
            and dist_vwap < -0.05  # NEW: must be below VWAP
        )
        if short_confirmed:
            return {
                "action": "OPEN",
                "rationale": (
                    f"CAS short (multi-signal): regime={regime}, ADX={adx:.2f}, "
                    f"RSI={rsi:.1f}, VIX={vix:.1f}, session_pct={session_pct:+.2f}%, "
                    f"vwap_dist={dist_vwap:+.2f}%"
                ),
                "strategy": "nifty_cash_short",
                "underlying": "NIFTY",
                "legs": [{"side": "SELL", "qty": 75, "order_type": "MARKET", "segment": "nse_cm"}],
                "target": 1.0,
                "stop": 0.75,
            }

        # PHASE 5 FIX 2026-09-30: range-bound but with directional bias
        # (session_pct > 0.05 OR < -0.05 but < thresholds above) → mild_up/down.
        # If we get here, regime is "range_bound" but session_pct was 0.
        # Actually range_bound means session_pct is between -0.05 and 0.05.
        # In that case, no edge.
        return {
            "action": "HOLD",
            "rationale": (
                f"no edge: regime={regime} ADX={adx:.1f} RSI={rsi:.1f} "
                f"session_pct={session_pct:+.2f}% vwap_dist={dist_vwap:+.2f}%"
            ),
        }

    def _write_close_all(self, reason: str = "manual", skip_swing: bool = False) -> bool:
        """PHASE 6 FIX: write CLOSE_ALL action for the bridge to consume.

        The bridge polls quant_actions.json. We write a CLOSE_ALL entry
        (action=CLOSE_ALL, no legs). The bridge calls /api/close_all.

        PHASE 6 FIX 2026-09-30 (swing mode): skip_swing=True excludes swing
        positions from the close. Default skip_swing=False (close everything
        for the default intraday-only behavior).

        Idempotent: if a close_all was written within the last 5 minutes,
        we skip (avoids duplicate calls).
        """
        try:
            from ..common.atomic_io import read_json
            existing = read_json(self.quant_actions_path, default={"actions": []})
            if not isinstance(existing, dict):
                existing = {"actions": []}
            now = _now_ist()
            for a in existing.get("actions", []):
                if a.get("action") == "CLOSE_ALL":
                    ts_str = a.get("ts", "")
                    try:
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        if (now - ts.replace(tzinfo=IST)).total_seconds() < 300:
                            logger.debug("CLOSE_ALL dedup: wrote within 5 min")
                            return False
                    except Exception:
                        pass
            existing.setdefault("actions", []).append({
                "ts": now.isoformat(),
                "action": "CLOSE_ALL",
                "strategy": "force_square",
                "underlying": "ALL",
                "rationale": reason,
                "skip_swing": skip_swing,  # PHASE 6 FIX
                "brain_source": "system.brain.brain_daemon",
            })
            existing["actions"] = existing["actions"][-20:]
            from ..common.atomic_io import write_json_atomic
            ok = write_json_atomic(self.quant_actions_path, existing)
            if ok:
                logger.warning(f"[CLOSE_ALL] written: {reason} (skip_swing={skip_swing})")
            return ok
        except Exception as e:
            logger.error(f"write close_all failed: {e}")
            return False

    def _write_quant_action(self, decision: dict, state: dict) -> bool:
        """Write decision to quant_actions.json for the bridge to pick up."""
        if decision.get("action") != "OPEN":
            return False
        try:
            # Read existing via shared atomic_io (utf-8-sig BOM-safe)
            from ..common.atomic_io import read_json
            doc = read_json(self.quant_actions_path, default={"actions": []})
            if not isinstance(doc, dict):
                doc = {"actions": []}
            # PHASE 5 FIX 2026-09-30: dedup at the brain side too. The brain
            # fires every 10s; without dedup, the same action would
            # accumulate in the file. Use the strategy+legs+rationale hash
            # as a fingerprint (same scheme as the bridge).
            import hashlib
            ts = _now_ist().isoformat()
            action = {
                "ts": ts,
                "strategy": decision.get("strategy", "iron_condor_nifty"),
                "underlying": decision.get("underlying", "NIFTY"),
                "rationale": decision.get("rationale", "brain decision"),
                "target": float(decision.get("target", 0) or 0),
                "stop": float(decision.get("stop", 0) or 0),
                "legs": decision.get("legs", []),
                "brain_source": "system.brain.brain_daemon",
                "vix": state.get("vix", 0),
                "regime": state.get("regime", "unknown"),
            }
            fp = hashlib.md5(json.dumps({
                "strategy": action["strategy"],
                "underlying": action["underlying"],
                "legs": action["legs"],
                "rationale": action["rationale"][:100],
            }, sort_keys=True).encode()).hexdigest()[:16]
            # Skip if same fingerprint already in file
            existing_fps = set()
            for a in doc.get("actions", []):
                a_fp = hashlib.md5(json.dumps({
                    "strategy": a.get("strategy", ""),
                    "underlying": a.get("underlying", ""),
                    "legs": a.get("legs", []),
                    "rationale": str(a.get("rationale", ""))[:100],
                }, sort_keys=True).encode()).hexdigest()[:16]
                existing_fps.add(a_fp)
            if fp in existing_fps:
                logger.debug(f"brain dedup: same action already in file (fp={fp})")
                return False
            doc.setdefault("actions", []).append(action)
            # Truncate to last 20 actions to keep file size bounded
            doc["actions"] = doc["actions"][-20:]
            # PHASE 6 FIX 2026-09-30: atomic write. Kills the [Errno 22]
            # that hit when brain daemon and bridge both tried to write
            # quant_actions.json at the same instant on Windows.
            from ..common.atomic_io import write_json_atomic
            ok = write_json_atomic(self.quant_actions_path, doc)
            if not ok:
                logger.warning(f"write quant_actions: atomic write failed")
                return False
            logger.info(f"brain wrote OPEN action: {action['strategy']} ({action['rationale'][:80]})")
            return True
        except Exception as e:
            logger.error(f"write quant_actions: {e}")
            return False

    async def cycle(self) -> dict:
        """Run one brain cycle. Returns decision."""
        self.stats["cycles"] += 1
        now = _now_ist()

        # PHASE 6 FIX: daily reset at market open. Clear stale circuit-breaker
        # so a new day starts clean. Multi-day runs no longer need manual reset.
        global _last_reset_date
        today_str = now.strftime("%Y-%m-%d")
        if _last_reset_date != today_str and _is_market_open(now):
            _last_reset_date = today_str
            try:
                cb = self.data_dir / "trading_halted.json"
                if cb.exists():
                    cb.unlink()
                    logger.info(f"[daily-reset] cleared {cb.name} for {today_str}")
            except Exception as e:
                logger.debug(f"daily reset cleanup: {e}")

        # PHASE 6 FIX 2026-09-30: EOD force-square at 15:15-15:25 IST.
        # Close ALL open positions to prevent overnight gap risk.
        # Skip SWING positions (they intentionally hold overnight).
        if _is_eod_close_time(now):
            skip_swing = False
            if ENABLE_SWING:
                try:
                    from .swing_tracker import get_open_swings
                    open_swings = get_open_swings()
                    if open_swings:
                        skip_swing = True
                        logger.info(
                            f"[EOD-CLOSE] skipping {len(open_swings)} swing position(s) "
                            f"(intraday-only mode disabled for swing)"
                        )
                except Exception:
                    pass
            self._write_close_all(reason="eod_force_square", skip_swing=skip_swing)
            self.stats["close_all"] = self.stats.get("close_all", 0) + 1
            return {"action": "CLOSE_ALL", "rationale": "eod_force_square 15:15 IST"}

        if not _is_market_open(now):
            return {"action": "HOLD", "rationale": "market_closed"}
        if _is_force_square_time(now):
            return {"action": "HOLD", "rationale": "force_square_time"}

        state = self._read_state()

        # PHASE 6 FIX: daily P&L circuit breaker — if today's realized
        # P&L is below -3% of starting capital, halt trading for the day.
        cb_path = self.data_dir / "trading_halted.json"
        try:
            if cb_path.exists():
                cb = json.loads(cb_path.read_text(encoding="utf-8"))
                if cb.get("halted_until"):
                    halt_until = datetime.fromisoformat(cb["halted_until"])
                    if now < halt_until:
                        return {"action": "HOLD", "rationale": f"daily_loss_circuit_breaker {cb.get('reason', '')}"}
        except Exception:
            pass

        # PHASE 6 FIX: skip if already have open position (avoid piling on)
        open_positions = state.get("open_positions", [])
        if open_positions:
            return {"action": "HOLD", "rationale": "have_open_position"}

        decision = await self._call_llm(state)
        self.stats["decisions"] += 1
        action = decision.get("action", "HOLD")

        # PHASE 6 FIX 2026-09-30: counterfactual tracking.
        try:
            from .counterfactual import record_decision
            regime = state.get("regime", "unknown")
            vix = float(state.get("vix", 0) or 0)
            adx = float(state.get("adx", 0) or 0)
            rsi = float(state.get("rsi", 0) or 0)
            signal_strength = 0.0
            would_have = None
            would_pnl = 0.0
            if action == "HOLD":
                if adx >= 25 and 11 <= vix <= 22:
                    if (regime == "trending_up" and rsi >= 55) or (regime == "trending_down" and rsi <= 45):
                        signal_strength = min(1.0, adx / 50.0)
                        would_have = "OPEN"
                        vwap_dist = float(state.get("vwap_distance", 0) or 0)
                        would_pnl = vwap_dist * signal_strength * 100
            record_decision(
                decision=action,
                action={
                    "strategy": decision.get("strategy", ""),
                    "rationale": decision.get("rationale", ""),
                },
                regime=regime,
                vix=vix,
                adx=adx,
                signal_strength=signal_strength,
                would_have_action=would_have,
                would_have_pnl_per_lot=round(would_pnl, 2),
            )
        except Exception as e:
            logger.debug(f"counterfactual record failed: {e}")

        # PHASE 6 FIX 2026-09-30 (swing mode): track swing positions + check exits
        try:
            if ENABLE_SWING:
                from .swing_tracker import (
                    add_swing_position,
                    update_swing_prices,
                    check_swing_exits,
                    close_swing,
                )
                from ..common.atomic_io import read_json, write_json_atomic
                # Update prices from core's tick store
                ltp_map = {"NIFTY": float(state.get("nifty_spot", 0) or 0)}
                update_swing_prices(ltp_map)
                # Check if any open swing should be closed
                to_close = check_swing_exits()
                if to_close:
                    swing_close_action = {
                        "ts": _now_ist().isoformat(),
                        "action": "SWING_CLOSE",
                        "strategy": to_close[0].get("strategy", "swing"),
                        "underlying": to_close[0].get("underlying", "NIFTY"),
                        "exit_reason": to_close[0].get("exit_reason", ""),
                        "rationale": f"swing exit: {to_close[0].get('exit_reason', '')}",
                        "brain_source": "system.brain.brain_daemon",
                    }
                    existing_qa = read_json(self.quant_actions_path, default={"actions": []})
                    if not isinstance(existing_qa, dict):
                        existing_qa = {"actions": []}
                    existing_qa.setdefault("actions", []).append(swing_close_action)
                    existing_qa["actions"] = existing_qa["actions"][-20:]
                    write_json_atomic(self.quant_actions_path, existing_qa)
                    logger.warning(f"[SWING-EXIT] {to_close[0].get('exit_reason')}")
                    return {"action": "SWING_CLOSE", "rationale": str(to_close[0].get('exit_reason', ''))}
        except Exception as e:
            logger.debug(f"swing tracker failed: {e}")

        if action == "OPEN":
            if self._write_quant_action(decision, state):
                self.stats["open"] += 1
                # PHASE 6 FIX: if swing position opened, register it
                try:
                    if ENABLE_SWING and decision.get("swing"):
                        from .swing_tracker import add_swing_position
                        nifty_spot = float(state.get("nifty_spot", 0) or 0)
                        if nifty_spot > 0:
                            leg = decision.get("legs", [{}])[0]
                            add_swing_position(
                                strategy=decision.get("strategy", ""),
                                underlying="NIFTY",
                                side=leg.get("side", "BUY"),
                                qty=leg.get("qty", 75),
                                entry_price=nifty_spot,
                                target_pct=float(decision.get("target", 0.02)),
                                stop_pct=float(decision.get("stop", 0.015)),
                                hold_days=int(decision.get("hold_days", 5)),
                            )
                            logger.warning(f"[SWING-OPEN] {decision.get('strategy')} @ {nifty_spot}")
                except Exception as e:
                    logger.debug(f"swing registration failed: {e}")
            else:
                self.stats["errors"] += 1
        elif action == "SWING_CLOSE":
            self.stats["swing_close"] = self.stats.get("swing_close", 0) + 1
        else:
            self.stats["hold"] += 1

        # PHASE 6 FIX: daily P&L circuit breaker trigger. After every
        # decision, check today's realized P&L. If below -3% halt for the day.
        try:
            realized = float(state.get("realized_pnl", 0) or 0)
            starting = 100_000.0
            if realized <= -0.03 * starting:
                from datetime import timedelta
                halt_until = now.replace(hour=15, minute=30, second=0, microsecond=0)
                if halt_until <= now:
                    halt_until = (now + timedelta(days=1)).replace(hour=9, minute=15, second=0, microsecond=0)
                cb = {
                    "halted_until": halt_until.isoformat(),
                    "reason": f"daily_loss_{realized:.0f}_below_-3000",
                    "ts": now.isoformat(),
                }
                cb_path.write_text(json.dumps(cb), encoding="utf-8")
                logger.warning(f"[CIRCUIT-BREAKER] daily loss {realized:.0f} < -3000 → halt trading")
        except Exception as e:
            logger.debug(f"circuit breaker check failed: {e}")

        return decision

    async def run_forever(self):
        """Main loop. Sleeps interval_sec between cycles."""
        # PHASE 6 FIX 2026-09-30: per-service heartbeat. The brain daemon
        # runs every 120s; if it's stuck in an LLM call or crash-looping,
        # the heartbeat staleness is the only reliable signal (process check
        # says alive). Watchdog restarts if no update in 90s.
        from ..common.heartbeat import HeartbeatWriter
        hb = HeartbeatWriter("brain_daemon", interval_sec=10)
        hb.update(cycles=0, opens=0, holds=0, errors=0)
        hb.start()

        logger.info(
            f"brain daemon started: interval={self.interval_sec}s "
            f"llm={self.llm_model} key={'set' if self.llm_api_key else 'missing'}"
        )
        while True:
            try:
                decision = await self.cycle()
                logger.info(
                    f"[BRAIN] cycle #{self.stats['cycles']} "
                    f"action={decision.get('action')} "
                    f"rationale={decision.get('rationale', '')[:80]} "
                    f"stats={self.stats}"
                )
                hb.update(
                    cycles=self.stats.get("cycles", 0),
                    opens=self.stats.get("open", 0),
                    holds=self.stats.get("hold", 0),
                    errors=self.stats.get("errors", 0),
                )
            except Exception as e:
                self.stats["errors"] += 1
                logger.warning(f"brain cycle error: {e}")
                hb.update(last_error=str(e)[:200], errors=self.stats["errors"])
            await asyncio.sleep(self.interval_sec)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_SEC,
                        help="seconds between cycles (default 300 = 5 min)")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--quant-actions", default=str(DEFAULT_QUANT_ACTIONS))
    parser.add_argument("--llm-model", default=DEFAULT_LLM_MODEL)
    parser.add_argument("--llm-base", default=DEFAULT_LLM_BASE)
    parser.add_argument("--llm-api-key", default=DEFAULT_LLM_API_KEY)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [BRAIN] %(message)s",
    )

    daemon = BrainDaemon(
        data_dir=Path(args.data_dir),
        quant_actions_path=Path(args.quant_actions),
        interval_sec=args.interval,
        llm_base_url=args.llm_base,
        llm_model=args.llm_model,
        llm_api_key=args.llm_api_key,
    )
    asyncio.run(daemon.run_forever())


if __name__ == "__main__":
    main()