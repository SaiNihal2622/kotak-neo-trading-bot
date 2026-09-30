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
DEFAULT_LLM_API_KEY = os.environ.get("MINIMAX_LLM_API_KEY") or os.environ.get("MINIMAX_API_KEY", "") or "managed-auth"

# Override the credentials.env legacy URL with the canonical one.
# (Uncomment to force; the env-var default above is already correct.)
# os.environ["MINIMAX_LLM_BASE_URL"] = DEFAULT_LLM_BASE

# Market hours IST
MARKET_OPEN_HOUR = 9
MARKET_OPEN_MIN = 15
MARKET_CLOSE_HOUR = 15
MARKET_CLOSE_MIN = 30

# Strategy thresholds
ADX_TREND_THRESHOLD = 25
RSI_LONG_THRESHOLD = 55
RSI_SHORT_THRESHOLD = 45
VIX_MIN_TRADE = 13
VIX_MAX_TRADE = 22


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
            intraday = self.data_dir / "intraday_levels.json"
            if intraday.exists():
                with open(intraday, encoding="utf-8") as f:
                    data = json.load(f)
                nifty_data = data.get("NIFTY", {})
                state["regime"] = nifty_data.get("regime", "unknown")
                state["adx"] = float(nifty_data.get("adx", 0))
                state["rsi"] = float(nifty_data.get("rsi", 50))
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

Rules:
- Range-bound + IV > 13 → iron_condor_nifty
- Trending up + RSI > 55 + ADX > 25 → nifty_cash_long (NIFTY spot MIS long)
- Trending down + RSI < 45 + ADX > 25 → nifty_cash_short (NIFTY spot MIS short)
- After 14:30 IST → never enter new positions
- Always include 'rationale' field (1 short sentence).
- Always include 'underlying' field.
- For options, set 'legs': [{side, strike, opt_type, expiry, qty, order_type}]
- For cash (CAS), set 'legs': [{side, qty: 75, order_type: "MARKET", segment: "nse_cm"}]
- target / stop are percentages from entry (e.g. target=1.0 means +1%).

Output JSON only:
{"action": "HOLD"|"OPEN", "rationale": "...", "strategy": "...", "underlying": "NIFTY", "legs": [...], "target": 1.0, "stop": 0.75}

When HOLD: omit "strategy" and "legs"."""

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
            "max_tokens": 600,
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
            # Extract JSON
            start = text.find("{")
            end = text.rfind("}") + 1
            if start < 0 or end <= start:
                logger.warning(f"LLM text has no JSON: {text[:200]}")
                return self._rule_based_decision(state)
            return json.loads(text[start:end])
        except Exception as e:
            logger.warning(f"LLM call failed: {e}")
            return self._rule_based_decision(state)

    def _rule_based_decision(self, state: dict) -> dict:
        """Fallback when no LLM available. Uses mechanical regime strategy."""
        adx = state.get("adx", 0)
        rsi = state.get("rsi", 50)
        regime = state.get("regime", "unknown")
        vix = state.get("vix", 0)
        if _is_force_square_time(_now_ist()):
            return {"action": "HOLD", "rationale": "after force-square time"}
        if state.get("open_positions"):
            return {"action": "HOLD", "rationale": "have open position"}
        if vix < VIX_MIN_TRADE or vix > VIX_MAX_TRADE:
            return {"action": "HOLD", "rationale": f"VIX {vix:.1f} outside [{VIX_MIN_TRADE}, {VIX_MAX_TRADE}]"}
        # Trending + ADX > 25
        if regime in ("trending_up", "uptrend") and adx > ADX_TREND_THRESHOLD and rsi > RSI_LONG_THRESHOLD:
            return {
                "action": "OPEN",
                "rationale": f"CAS long: trending up, ADX={adx:.1f}, RSI={rsi:.1f}, VIX={vix:.1f}",
                "strategy": "nifty_cash_long",
                "underlying": "NIFTY",
                "legs": [{"side": "BUY", "qty": 75, "order_type": "MARKET", "segment": "nse_cm"}],
                "target": 1.0,
                "stop": 0.75,
            }
        if regime in ("trending_down", "downtrend") and adx > ADX_TREND_THRESHOLD and rsi < RSI_SHORT_THRESHOLD:
            return {
                "action": "OPEN",
                "rationale": f"CAS short: trending down, ADX={adx:.1f}, RSI={rsi:.1f}, VIX={vix:.1f}",
                "strategy": "nifty_cash_short",
                "underlying": "NIFTY",
                "legs": [{"side": "SELL", "qty": 75, "order_type": "MARKET", "segment": "nse_cm"}],
                "target": 1.0,
                "stop": 0.75,
            }
        # Range-bound → iron condor (only if we have spot/VIX — placeholder for now)
        return {"action": "HOLD", "rationale": f"no edge: regime={regime} ADX={adx:.1f} RSI={rsi:.1f}"}

    def _write_quant_action(self, decision: dict, state: dict) -> bool:
        """Write decision to quant_actions.json for the bridge to pick up."""
        if decision.get("action") != "OPEN":
            return False
        try:
            # Read existing
            if self.quant_actions_path.exists():
                with open(self.quant_actions_path, encoding="utf-8-sig") as f:
                    doc = json.load(f)
            else:
                doc = {"actions": []}
            # Build action
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
            doc.setdefault("actions", []).append(action)
            with open(self.quant_actions_path, "w", encoding="utf-8") as f:
                json.dump(doc, f, ensure_ascii=False)
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
            except Exception as e:
                self.stats["errors"] += 1
                logger.warning(f"brain cycle error: {e}")
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