"""Kotak Brain — LLM-based daily decision engine.

Sits alongside the existing kotak_bot. Periodically (every 15 min during
market hours, once at open, once at close) it:
  1. Reads current market state (paper_state.json, regime, VIX, news headlines)
  2. Calls MiniMax M2.7-highspeed to get a high-level "today's bias" + risk budget
  3. Writes the decision to data_cache/brain_state.json (read-only for kotak_bot)
  4. Logs to data_cache/brain.log for user inspection

This does NOT modify the existing bot. It's an *advisory* layer — the user
can read brain_state.json to know what the LLM thinks the day should look
like. The bot's own StrategySelector still picks the actual trade.

Design goals:
  - At most ~10 LLM calls per day (cheap)
  - Always has a deterministic fallback (never blocks on LLM failure)
  - Persists state so a crash doesn't lose context
  - Single file, zero new dependencies (uses existing kotak_bot + LLMNewsJudge)
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta
from pathlib import Path

# repo root
ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(ROOT))

# ---- Load credentials.env (must happen before any LLM call) ----
# The brain can be invoked directly (cron, scheduler) without env vars set.
# We load from config/credentials.env the same way kotak_bot's modules do.
try:
    from dotenv import load_dotenv
    _env_file = ROOT / "config" / "credentials.env"
    if _env_file.exists():
        load_dotenv(str(_env_file))
except Exception as _e:
    # Non-fatal: env may already be set by parent process
    pass

from loguru import logger  # noqa: E402

# -------- config --------
BRAIN_STATE_PATH = ROOT / "data_cache" / "brain_state.json"
BRAIN_LOG_PATH = ROOT / "data_cache" / "brain.log"
PAPER_STATE_PATH = ROOT / "data_cache" / "paper_state.json"

# how often to re-evaluate during market hours (minutes)
RE_EVAL_MINUTES = 15
# how long to keep LLM responses cached (seconds)
LLM_CACHE_TTL = 900
# hard cap on LLM calls per day to control cost
MAX_CALLS_PER_DAY = 100


@dataclass
class BrainDecision:
    """One LLM-generated decision snapshot."""
    timestamp: str
    ist_time: str
    bias: str               # 'bullish' | 'bearish' | 'neutral' | 'cautious'
    confidence: float       # 0..1
    risk_budget_pct: float  # % of capital to deploy today (0..100)
    max_positions: int
    preferred_strategies: list[str]
    avoid_strategies: list[str]
    news_summary: str
    rationale: str
    source: str             # 'minimax' | 'fallback'
    call_count_today: int
    next_eval_at: str


@dataclass
class BrainState:
    """Persistent brain state (decisions + counters)."""
    today_date: str = ""
    call_count_today: int = 0
    last_decision: BrainDecision | None = None
    history: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "today_date": self.today_date,
            "call_count_today": self.call_count_today,
            "last_decision": asdict(self.last_decision) if self.last_decision else None,
            "history": self.history[-50:],  # cap history
        }


# -------- helpers --------

def _now_ist_str() -> str:
    from kotak_bot.utils.clock import now_ist
    return now_ist().strftime("%Y-%m-%d %H:%M:%S")


def _today_str() -> str:
    from kotak_bot.utils.clock import now_ist
    return now_ist().strftime("%Y-%m-%d")


def _load_paper_state() -> dict:
    """Read paper trading state (cash, pnl, positions). Never raises."""
    try:
        if not PAPER_STATE_PATH.exists():
            return {}
        with open(PAPER_STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"brain: could not read paper_state.json: {e}")
        return {}


def _load_existing_state() -> BrainState:
    try:
        if BRAIN_STATE_PATH.exists():
            with open(BRAIN_STATE_PATH, "r", encoding="utf-8") as f:
                raw = json.load(f)
            s = BrainState(
                today_date=raw.get("today_date", ""),
                call_count_today=int(raw.get("call_count_today", 0)),
                history=list(raw.get("history", [])),
            )
            if raw.get("last_decision"):
                s.last_decision = BrainDecision(**raw["last_decision"])
            return s
    except Exception as e:
        logger.warning(f"brain: could not read brain_state.json: {e}")
    return BrainState()


def _save_state(state: BrainState) -> None:
    try:
        BRAIN_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = BRAIN_STATE_PATH.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state.to_dict(), f, indent=2)
        tmp.replace(BRAIN_STATE_PATH)
    except Exception as e:
        logger.error(f"brain: could not save brain_state.json: {e}")


# -------- prompt + LLM call --------

def _build_prompt(paper: dict, market_ctx: dict) -> str:
    """Build the daily-bias prompt for the LLM."""
    pos = paper.get("positions", {}) or {}
    open_count = len(pos)
    cash = paper.get("cash", 100000)
    realized = paper.get("realized_pnl", 0.0)
    margin = paper.get("margin", {})
    avail = margin.get("available", cash)

    regime = market_ctx.get("regime", "unknown")
    adx = market_ctx.get("adx", 0.0)
    trend = market_ctx.get("trend_strength", 0.0)
    iv_rank = market_ctx.get("iv_rank", 0.0)
    vix = market_ctx.get("india_vix", 14.0)
    news_sent = market_ctx.get("news_sentiment", 0.0)
    upcoming_event = market_ctx.get("upcoming_event", "")

    # ---- THESIS BLOCK (if thesis_engine ran recently) ----
    thesis_block = ""
    if market_ctx.get("thesis_source") == "thesis_engine":
        thesis_block = f"""
THESIS (from thesis_engine, refreshed every 90 min):
- Bias (proposed): {market_ctx.get('thesis_bias','?')} (confidence {market_ctx.get('thesis_confidence',0):.0%})
- Risk budget (proposed): {market_ctx.get('thesis_risk_budget',0):.0f}% of capital
- Max positions (proposed): see below
- OI walls: support {market_ctx.get('oi_support','-')} / resistance {market_ctx.get('oi_resistance','-')}
- Max pain: {market_ctx.get('max_pain','-')}
- PCR: {market_ctx.get('pcr','-')}
- GEX total: {market_ctx.get('gex_total','-')}
- Narrative: {market_ctx.get('thesis_narrative','')}
- Triggers: {market_ctx.get('thesis_triggers',{})}
- Specific strikes (OI-aware): {market_ctx.get('thesis_specific_strikes')}

You may agree, refine, or override the thesis bias — but if you disagree, your
rationale MUST explain the data conflict (OI vs news vs cross-market).
"""

    return f"""You are a senior Indian options day-trader. Decide today's trading bias and risk budget.

CURRENT STATE (IST {market_ctx.get('ist_time', '?')}, NSE paper-trading):
- Capital: ₹{cash:,.0f} cash, ₹{avail:,.0f} available margin
- Open positions: {open_count}
- Realized PnL (today): ₹{realized:,.0f}
- Regime: {regime} (ADX={adx:.1f}, trend={trend:+.2f})
- IV rank: {iv_rank:.0f}/100, India VIX: {vix:.1f}
- News sentiment (last 4h): {news_sent:+.2f} (-1 bearish, +1 bullish)
- Upcoming event: {upcoming_event or 'none'}
{thesis_block}
STRATEGY LIBRARY: iron_condor, iron_butterfly, jade_lizard, short_strangle, calendar,
bull_call_vertical, bear_put_vertical, long_call, long_put, long_straddle, event_straddle.

Respond ONLY in valid JSON (no markdown, no prose):
{{
  "bias": "<bullish|bearish|neutral|cautious>",
  "confidence": <float 0.0 to 1.0>,
  "risk_budget_pct": <float 0.0 to 100.0>,   // % of available capital to deploy today
  "max_positions": <int 0 to 6>,
  "preferred_strategies": ["<strat1>", ...],  // top 3 strategies for this regime
  "avoid_strategies": ["<strat1>", ...],     // strategies to skip today
  "news_summary": "<one short sentence on news>",
  "rationale": "<one short sentence explaining the bias>"
}}"""


def _call_llm(prompt: str) -> str:
    """Call MiniMax M2.7 directly (same endpoint as LLMNewsJudge)."""
    import httpx
    base = os.environ.get(
        "MINIMAX_LLM_BASE_URL",
        "https://agent.minimax.io/mavis/api/v1/llm/v1",
    )
    api_key = os.environ.get("MINIMAX_LLM_API_KEY", "managed-auth")
    model = os.environ.get("BRAIN_MODEL", "MiniMax-M3")
    url = f"{base.rstrip('/')}/messages"
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "Authorization": f"Bearer {api_key}",
        "anthropic-version": "2023-06-01",
    }
    body = {
        "model": model,
        "max_tokens": 800,
        "temperature": 0.2,
        "system": (
            "You are a precise financial analyst. "
            "You MUST respond with a single valid JSON object inside a 'text' content block. "
            "Required keys: bias (bullish|bearish|neutral|cautious), confidence (0..1 float), "
            "risk_budget_pct (0..100 float), max_positions (int 0..6), preferred_strategies (list of strings), "
            "avoid_strategies (list of strings), news_summary (string), rationale (string). "
            "Return ONLY the JSON object. No markdown, no prose, no preamble, no explanation outside the JSON."
        ),
        "messages": [{"role": "user", "content": prompt}],
    }
    with httpx.Client(timeout=45) as c:
        r = c.post(url, headers=headers, json=body)
    if r.status_code != 200:
        raise RuntimeError(f"LLM HTTP {r.status_code}: {r.text[:200]}")
    data = r.json()
    # Try text block first, then thinking block, then any text-like content
    candidates: list[str] = []
    for block in data.get("content", []):
        btype = block.get("type", "")
        if btype == "text":
            candidates.append(block.get("text", ""))
        elif btype == "thinking":
            candidates.append(block.get("thinking", ""))
    # Also scan for any string content (rare)
    if not candidates and isinstance(data.get("content"), list):
        for block in data["content"]:
            for k, v in block.items():
                if isinstance(v, str) and len(v) > 5:
                    candidates.append(v)
    for c in candidates:
        if c and "{" in c and "}" in c:
            return c[c.find("{"):c.rfind("}") + 1]
    if not candidates:
        raise RuntimeError(f"no text/thinking in LLM response: {str(data)[:200]}")
    return candidates[0]


def _fallback_decision(market_ctx: dict) -> BrainDecision:
    """Deterministic fallback if LLM fails. Use regime + VIX to pick a bias."""
    regime = market_ctx.get("regime", "unknown")
    vix = market_ctx.get("india_vix", 14.0)
    if vix > 22:
        bias, risk = "cautious", 0.0
    elif regime == "trending":
        bias, risk = "bullish" if market_ctx.get("trend_strength", 0) > 0 else "bearish", 35.0
    elif regime == "range":
        bias, risk = "neutral", 30.0
    elif regime == "volatile":
        bias, risk = "cautious", 10.0
    else:
        bias, risk = "neutral", 20.0
    return BrainDecision(
        timestamp=datetime.utcnow().isoformat() + "Z",
        ist_time=_now_ist_str(),
        bias=bias,
        confidence=0.3,
        risk_budget_pct=risk,
        max_positions=2 if risk > 0 else 0,
        preferred_strategies=["iron_condor", "short_strangle"] if regime == "range" else [],
        avoid_strategies=["long_straddle"] if vix > 22 else [],
        news_summary="(no LLM; using fallback)",
        rationale=f"fallback: regime={regime}, vix={vix:.1f}",
        source="fallback",
        call_count_today=0,
        next_eval_at="",
    )


def _parse_llm(raw: str, market_ctx: dict, call_count: int) -> BrainDecision:
    try:
        d = json.loads(raw)
        return BrainDecision(
            timestamp=datetime.utcnow().isoformat() + "Z",
            ist_time=_now_ist_str(),
            bias=str(d.get("bias", "neutral")).lower(),
            confidence=float(d.get("confidence", 0.5)),
            risk_budget_pct=float(d.get("risk_budget_pct", 25.0)),
            max_positions=int(d.get("max_positions", 2)),
            preferred_strategies=list(d.get("preferred_strategies", [])),
            avoid_strategies=list(d.get("avoid_strategies", [])),
            news_summary=str(d.get("news_summary", ""))[:200],
            rationale=str(d.get("rationale", ""))[:300],
            source="minimax",
            call_count_today=call_count,
            next_eval_at="",
        )
    except Exception as e:
        logger.warning(f"brain: parse failed ({e}); using fallback")
        d = _fallback_decision(market_ctx)
        d.call_count_today = call_count
        return d


# -------- market context --------

def _gather_market_context() -> dict:
    """Best-effort market context without breaking if any module is down."""
    from kotak_bot.utils.clock import now_ist, get_india_vix
    from kotak_bot.utils.clock import market_session

    ctx: dict = {
        "ist_time": now_ist().strftime("%H:%M"),
        "session": market_session(),
        "regime": "unknown",
        "adx": 0.0,
        "trend_strength": 0.0,
        "iv_rank": 0.0,
        "india_vix": get_india_vix(),
        "news_sentiment": 0.0,
        "upcoming_event": "",
    }

    # ---- THESIS INJECTION (preferred over raw regime detection) ----
    # If the thesis_engine has run recently (< 90 min), use its regime +
    # bias as the primary input. LLM still gets the final say, but
    # it's now grounded in OI + macro + cross-market + news + research.
    try:
        thesis_path = ROOT / "data_cache" / "thesis" / "latest.json"
        if thesis_path.exists():
            import json as _json
            from datetime import datetime as _dt
            t = _json.loads(thesis_path.read_text(encoding="utf-8"))
            ts = t.get("ts") or ""
            try:
                age_min = (now_ist() - _dt.fromisoformat(ts)).total_seconds() / 60
            except Exception:
                age_min = 999
            if age_min < 90 and t.get("regime"):
                ctx["regime"] = t["regime"]
                ctx["thesis_bias"] = t.get("bias", "neutral")
                ctx["thesis_confidence"] = float(t.get("confidence", 0.0))
                ctx["thesis_risk_budget"] = float(t.get("risk_budget_pct", 0))
                ctx["thesis_narrative"] = t.get("narrative", "")
                ctx["thesis_specific_strikes"] = t.get("specific_strikes")
                ctx["thesis_triggers"] = t.get("triggers", {})
                ctx["thesis_source"] = "thesis_engine"
                # OI-derived context
                oi = (t.get("data") or {}).get("oi") or {}
                if oi.get("max_pain"):
                    ctx["max_pain"] = oi["max_pain"]
                if oi.get("resistance"):
                    ctx["oi_resistance"] = oi["resistance"]
                if oi.get("support"):
                    ctx["oi_support"] = oi["support"]
                if oi.get("pcr") is not None:
                    ctx["pcr"] = oi["pcr"]
                if oi.get("gex_total") is not None:
                    ctx["gex_total"] = oi["gex_total"]
                # news + macro
                news = (t.get("data") or {}).get("news") or {}
                ctx["news_sentiment"] = float(news.get("score", 0.0))
                macro = (t.get("data") or {}).get("macro") or {}
                evt = macro.get("next_event") or {}
                if isinstance(evt, dict) and macro.get("window_min") is not None:
                    ctx["upcoming_event"] = f"{evt.get('name','event')} in {int(macro['window_min'])}m"
    except Exception as e:
        logger.debug(f"brain: thesis injection best-effort failed: {e}")
    # try to read latest regime from kotak_bot's data cache (best-effort)
    try:
        from kotak_bot.signals.regime import RegimeDetector
        from kotak_bot.data.historical import HistoricalData
        rd = RegimeDetector()
        # fetch last 30 daily candles for NIFTY
        hd = HistoricalData()
        df = hd.get_equity_ohlc("NIFTY", days=30, interval="1d")
        vix = float(ctx.get("india_vix") or 14.0)
        momentum = 0.0
        spot = 0.0
        if df is not None and not df.empty and len(df) >= 5:
            closes = df["close"].astype(float)
            spot = float(closes.iloc[-1])
            # 1-day momentum: % change from yesterday's close to today's close
            if len(closes) >= 2:
                momentum = (closes.iloc[-1] - closes.iloc[-2]) / closes.iloc[-2]
        # iv_rank is not directly available; use 50 (neutral) as fallback
        # this can be improved by reading the option-chain from kotak_research
        state = rd.detect(df, vix=vix, iv_rank=50.0, momentum=momentum, spot=spot, atm=spot)
        ctx["regime"] = state.regime.value if hasattr(state.regime, "value") else str(state.regime)
        ctx["adx"] = float(state.adx)
        ctx["trend_strength"] = float(state.adx)  # alias for compatibility
        ctx["iv_rank"] = float(state.iv_rank)
        ctx["regime_reason"] = state.reason
        ctx["regime_confidence"] = float(state.confidence)
    except Exception as e:
        logger.debug(f"brain: regime detection best-effort failed: {e}")
    return ctx


# -------- main loop --------

def evaluate_once() -> BrainDecision:
    """Run one evaluation cycle. Returns the decision (also persisted)."""
    state = _load_existing_state()
    today = _today_str()
    if state.today_date != today:
        # new day — reset counter
        state.today_date = today
        state.call_count_today = 0

    paper = _load_paper_state()
    market_ctx = _gather_market_context()
    call_count = state.call_count_today + 1

    if call_count > MAX_CALLS_PER_DAY:
        logger.info(f"brain: hit daily cap ({MAX_CALLS_PER_DAY}); using fallback")
        decision = _fallback_decision(market_ctx)
        decision.call_count_today = state.call_count_today
    else:
        try:
            prompt = _build_prompt(paper, market_ctx)
            raw = _call_llm(prompt)
            decision = _parse_llm(raw, market_ctx, call_count)
            state.call_count_today = call_count
        except Exception as e:
            logger.warning(f"brain: LLM call failed ({e}); using fallback")
            decision = _fallback_decision(market_ctx)
            decision.call_count_today = call_count  # still counts as a "decision"

    # schedule next eval
    from kotak_bot.utils.clock import now_ist
    next_at = (now_ist() + timedelta(minutes=RE_EVAL_MINUTES)).strftime("%H:%M:%S")
    decision.next_eval_at = next_at

    state.last_decision = decision
    state.history.append({
        "ts": decision.timestamp,
        "ist": decision.ist_time,
        "bias": decision.bias,
        "source": decision.source,
        "risk_pct": decision.risk_budget_pct,
    })
    _save_state(state)
    logger.info(
        f"brain: bias={decision.bias} conf={decision.confidence:.2f} "
        f"risk={decision.risk_budget_pct:.0f}% max_pos={decision.max_positions} "
        f"source={decision.source} next={next_at}"
    )

    # Generate concrete trade actions for the executor to act on
    try:
        _write_trade_actions(decision, paper, market_ctx)
    except Exception as e:
        logger.warning(f"brain: action generation failed: {e}")

    return decision


# -------- trade actions (executor contract) --------

ACTIONS_PATH = ROOT / "data_cache" / "brain_actions.json"


def _write_trade_actions(decision, paper, market_ctx) -> None:
    """Translate bias into concrete orders for the executor.

    Output schema (data_cache/brain_actions.json):
    {
      "ts": "...",
      "ist_time": "...",
      "bias": "...",
      "source": "...",
      "actions": [
        {
          "id": "act-<uuid>",
          "type": "OPEN" | "CLOSE" | "HOLD",
          "strategy": "iron_condor" | ...,
          "underlying": "NIFTY",
          "expiry": "YYYY-MM-DD",
          "legs": [
            {"side":"SELL","strike":24600,"option_type":"CE","qty":75,"price":59.72},
            ...
          ],
          "rationale": "...",
          "ttl_sec": 300,
          "executed": false
        }
      ]
    }
    """
    import uuid as _uuid
    from kotak_bot.utils.clock import now_ist, is_market_open, market_session
    actions: list[dict] = []
    open_positions = paper.get("positions", {}) or {}
    open_count = len(open_positions)

    # Only act during active market sessions
    if market_session() not in ("pre_open", "opening", "regular", "closing"):
        payload = {
            "ts": datetime.utcnow().isoformat() + "Z",
            "ist_time": _now_ist_str(),
            "bias": decision.bias,
            "source": decision.source,
            "actions": actions,
            "note": "market_closed",
        }
        ACTIONS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return

    # HOLD: no new entries, just close risky stuff if regime turned cautious
    if decision.bias in ("cautious",) or decision.risk_budget_pct < 5:
        # close everything (square off)
        for sym, pos in open_positions.items():
            actions.append({
                "id": f"act-{_uuid.uuid4().hex[:8]}",
                "type": "CLOSE",
                "strategy": "exit",
                "underlying": pos.get("underlying", "NIFTY"),
                "symbol": sym,
                "side": "BUY" if pos.get("qty", 0) < 0 else "SELL",
                "qty": abs(int(pos.get("qty", 0))),
                "rationale": f"bias={decision.bias} -> flatten",
                "ttl_sec": 120,
                "executed": False,
            })

    # OPEN: only if risk budget > 0 and we have headroom
    elif decision.bias in ("bullish", "bearish", "neutral") and open_count < decision.max_positions and decision.risk_budget_pct >= 10:
        # paper capital: aim to deploy ~risk_budget_pct of cash
        cash = float(paper.get("cash", 100000))
        deploy = cash * (decision.risk_budget_pct / 100.0) / max(1, decision.max_positions)
        # Translate bias into a single multi-leg option structure
        if "iron_condor" in decision.preferred_strategies or decision.bias == "neutral":
            actions.append(_build_iron_condor(decision, deploy))
        elif "short_strangle" in decision.preferred_strategies:
            actions.append(_build_short_strangle(decision, deploy))
        elif "bull_call_vertical" in decision.preferred_strategies or decision.bias == "bullish":
            actions.append(_build_bull_call_vertical(decision, deploy))
        elif "bear_put_vertical" in decision.preferred_strategies or decision.bias == "bearish":
            actions.append(_build_bear_put_vertical(decision, deploy))
        else:
            # default to iron condor
            actions.append(_build_iron_condor(decision, deploy))

    payload = {
        "ts": datetime.utcnow().isoformat() + "Z",
        "ist_time": _now_ist_str(),
        "bias": decision.bias,
        "source": decision.source,
        "max_positions": decision.max_positions,
        "actions": actions,
    }
    ACTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    ACTIONS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info(f"brain: wrote {len(actions)} action(s) to {ACTIONS_PATH.name}")


def _next_weekly_expiry() -> str:
    """Return next weekly Thursday expiry (YYYY-MM-DD)."""
    from datetime import timedelta
    today = datetime.now()
    days_to_thu = (3 - today.weekday()) % 7
    if days_to_thu == 0 and today.hour >= 15:
        days_to_thu = 7
    expiry = today + timedelta(days=days_to_thu)
    return expiry.strftime("%Y-%m-%d")


def _atm_strike(underlying: str = "NIFTY") -> int:
    """Approximate ATM strike from spot LTP if available, else round number."""
    # NIFTY lot = 75, BANKNIFTY lot = 30; strikes are multiples of 50 (NIFTY) / 100 (BN)
    # Use a sensible default since we don't have live LTP in the brain context
    if underlying == "BANKNIFTY":
        return 52000
    return 24600


def _build_iron_condor(decision, deploy_amount: float) -> dict:
    """Sell OTM put spread + OTM call spread around ATM."""
    import uuid as _uuid
    underlying = "NIFTY"
    atm = _atm_strike(underlying)
    lot = 75
    # OTM wings ~ Rs.200 away from ATM for NIFTY weekly
    short_put_strike = atm - 200
    long_put_strike = atm - 400
    short_call_strike = atm + 200
    long_call_strike = atm + 400
    expiry = _next_weekly_expiry()
    return {
        "id": f"act-{_uuid.uuid4().hex[:8]}",
        "type": "OPEN",
        "strategy": "iron_condor",
        "underlying": underlying,
        "expiry": expiry,
        "lot_size": lot,
        "expected_deploy": round(deploy_amount, 0),
        "legs": [
            {"side": "SELL", "option_type": "PE", "strike": short_put_strike, "qty": lot, "limit_price": 0.0},
            {"side": "BUY",  "option_type": "PE", "strike": long_put_strike,  "qty": lot, "limit_price": 0.0},
            {"side": "SELL", "option_type": "CE", "strike": short_call_strike, "qty": lot, "limit_price": 0.0},
            {"side": "BUY",  "option_type": "CE", "strike": long_call_strike, "qty": lot, "limit_price": 0.0},
        ],
        "rationale": f"bias={decision.bias} -> iron condor @ {atm}, ±200 wings",
        "ttl_sec": 300,
        "executed": False,
    }


def _build_short_strangle(decision, deploy_amount: float) -> dict:
    import uuid as _uuid
    underlying = "NIFTY"
    atm = _atm_strike(underlying)
    lot = 75
    short_put_strike = atm - 300
    short_call_strike = atm + 300
    expiry = _next_weekly_expiry()
    return {
        "id": f"act-{_uuid.uuid4().hex[:8]}",
        "type": "OPEN",
        "strategy": "short_strangle",
        "underlying": underlying,
        "expiry": expiry,
        "lot_size": lot,
        "expected_deploy": round(deploy_amount, 0),
        "legs": [
            {"side": "SELL", "option_type": "PE", "strike": short_put_strike, "qty": lot, "limit_price": 0.0},
            {"side": "SELL", "option_type": "CE", "strike": short_call_strike, "qty": lot, "limit_price": 0.0},
        ],
        "rationale": f"bias={decision.bias} -> naked strangle @ {atm}, ±300 wings",
        "ttl_sec": 300,
        "executed": False,
    }


def _build_bull_call_vertical(decision, deploy_amount: float) -> dict:
    import uuid as _uuid
    underlying = "NIFTY"
    atm = _atm_strike(underlying)
    lot = 75
    long_call_strike = atm
    short_call_strike = atm + 200
    expiry = _next_weekly_expiry()
    return {
        "id": f"act-{_uuid.uuid4().hex[:8]}",
        "type": "OPEN",
        "strategy": "bull_call_vertical",
        "underlying": underlying,
        "expiry": expiry,
        "lot_size": lot,
        "expected_deploy": round(deploy_amount, 0),
        "legs": [
            {"side": "BUY",  "option_type": "CE", "strike": long_call_strike, "qty": lot, "limit_price": 0.0},
            {"side": "SELL", "option_type": "CE", "strike": short_call_strike, "qty": lot, "limit_price": 0.0},
        ],
        "rationale": f"bias=bullish -> bull call vertical @ {atm}/{atm+200}",
        "ttl_sec": 300,
        "executed": False,
    }


def _build_bear_put_vertical(decision, deploy_amount: float) -> dict:
    import uuid as _uuid
    underlying = "NIFTY"
    atm = _atm_strike(underlying)
    lot = 75
    long_put_strike = atm
    short_put_strike = atm - 200
    expiry = _next_weekly_expiry()
    return {
        "id": f"act-{_uuid.uuid4().hex[:8]}",
        "type": "OPEN",
        "strategy": "bear_put_vertical",
        "underlying": underlying,
        "expiry": expiry,
        "lot_size": lot,
        "expected_deploy": round(deploy_amount, 0),
        "legs": [
            {"side": "BUY",  "option_type": "PE", "strike": long_put_strike, "qty": lot, "limit_price": 0.0},
            {"side": "SELL", "option_type": "PE", "strike": short_put_strike, "qty": lot, "limit_price": 0.0},
        ],
        "rationale": f"bias=bearish -> bear put vertical @ {atm}/{atm-200}",
        "ttl_sec": 300,
        "executed": False,
    }


def main() -> int:
    """CLI: `python kotak_brain.py [--once]` — runs one cycle, or loops every RE_EVAL_MINUTES."""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Run a single evaluation then exit")
    args = parser.parse_args()

    # ensure log path exists
    BRAIN_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logger.add(str(BRAIN_LOG_PATH), rotation="1 day", retention="14 days", level="INFO")

    logger.info(f"brain: starting (once={args.once})")
    if args.once:
        evaluate_once()
        logger.info("brain: --once complete")
        return 0

    # loop
    while True:
        try:
            from kotak_bot.utils.clock import now_ist, market_session
            session = market_session()
            # only run during market sessions (or pre_open for early context)
            if session in ("pre_open", "opening", "regular", "closing"):
                evaluate_once()
            else:
                logger.debug(f"brain: market {session}, sleeping")
        except KeyboardInterrupt:
            logger.info("brain: stopped by user")
            return 0
        except Exception as e:
            logger.exception(f"brain: loop error: {e}")
        time.sleep(RE_EVAL_MINUTES * 60)


if __name__ == "__main__":
    sys.exit(main())
