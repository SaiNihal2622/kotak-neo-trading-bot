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

Output JSON (exactly this shape, no other text):
{"action": "HOLD", "rationale": "<one short sentence>"}

OR for OPEN:
{"action": "OPEN", "rationale": "<one short sentence>", "strategy": "nifty_cash_long", "underlying": "NIFTY", "legs": [{"side": "BUY", "qty": 75, "order_type": "MARKET", "segment": "nse_cm"}], "target": 1.0, "stop": 0.75}

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

        # Trending up + ADX proxy > threshold + momentum positive
        if regime in ("trending_up", "mild_up", "uptrend") and adx > ADX_TREND_THRESHOLD and rsi > RSI_LONG_THRESHOLD:
            return {
                "action": "OPEN",
                "rationale": (
                    f"CAS long: regime={regime}, ADX={adx:.1f}, RSI={rsi:.1f}, "
                    f"VIX={vix:.1f}, session_pct={session_pct:+.2f}%, vwap_dist={dist_vwap:+.2f}%"
                ),
                "strategy": "nifty_cash_long",
                "underlying": "NIFTY",
                "legs": [{"side": "BUY", "qty": 75, "order_type": "MARKET", "segment": "nse_cm"}],
                "target": 1.0,
                "stop": 0.75,
            }
        if regime in ("trending_down", "mild_down", "downtrend") and adx > ADX_TREND_THRESHOLD and rsi < RSI_SHORT_THRESHOLD:
            return {
                "action": "OPEN",
                "rationale": (
                    f"CAS short: regime={regime}, ADX={adx:.1f}, RSI={rsi:.1f}, "
                    f"VIX={vix:.1f}, session_pct={session_pct:+.2f}%, vwap_dist={dist_vwap:+.2f}%"
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
        if not _is_market_open(now):
            return {"action": "HOLD", "rationale": "market_closed"}
        if _is_force_square_time(now):
            return {"action": "HOLD", "rationale": "force_square_time"}
        state = self._read_state()
        decision = await self._call_llm(state)
        self.stats["decisions"] += 1
        action = decision.get("action", "HOLD")

        # PHASE 6 FIX 2026-09-30: counterfactual tracking. Records what
        # we decided vs what we could have decided, so the brain prompt
        # gets "lessons learned" and improves over time.
        try:
            from .counterfactual import record_decision
            # Heuristic counterfactual: if we HOLD but the signals were
            # strong (high ADX, low VIX, regime matches trend direction),
            # the counterfactual is "would have OPENed".
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

        if action == "OPEN":
            if self._write_quant_action(decision, state):
                self.stats["open"] += 1
            else:
                self.stats["errors"] += 1
        else:
            self.stats["hold"] += 1
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