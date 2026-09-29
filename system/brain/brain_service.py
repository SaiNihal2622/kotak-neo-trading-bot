"""Brain service — proposes plans via /api/plan (the new event-sourced core).

The legacy brain (scripts/quant_service.py) writes JSON files directly:
- data_cache/brain_actions.json (proposals)
- data_cache/mavis_force_action.json (commands)

The new brain:
- Reads state from /api/state (single source of truth)
- Proposes plans via /api/plan (validates via pre-flight before broker)
- Subscribes to /ws for live state updates
- NEVER writes files; communicates via the core's HTTP API

Flow:
1. Tick (every 60s during market hours, 5min off-hours)
2. Read state from /api/state
3. Build decision context (positions, ticks, regime, etc.)
4. Call LLM (anthropic or openai) for plan recommendation
5. POST plan to /api/plan (pre-flight validates; rejects bad plans in 100ms)
6. If accepted, core emits order events; broker executes; positions update via WS

The brain is intentionally simple. The CORE does the heavy lifting:
- Pre-flight validation
- Atomic plan execution
- Position tracking
- Audit log
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import httpx
from pydantic import BaseModel, Field, validator


logger = logging.getLogger(__name__)


IST = timezone(timedelta(hours=5, minutes=30))


# ----- Pydantic schemas (mirror core/api/server.py) -----

class OrderSchema(BaseModel):
    client_order_id: str = ""
    symbol: str
    underlying: str = "NIFTY"
    side: str = Field(..., pattern="^(BUY|SELL)$")
    qty: int = Field(..., gt=0)
    order_type: str = "MARKET"
    product: str = "MIS"
    price: float = 0.0
    tag: str = "BRAIN"
    strike: float = 0.0
    option_type: str = ""
    expiry: str = ""
    exchange: str = "NFO"


class PlanSchema(BaseModel):
    strategy: str
    underlying: str = "NIFTY"
    legs: list[OrderSchema]
    target: float = 0.0
    stop: float = 0.0
    confidence: float = 0.0
    reason: str = ""
    dry_run: bool = True


# ----- LLM client (stub — wire up to real provider) -----

class LLMClient:
    """Anthropic or OpenAI client. Stub here — wire up in production."""

    def __init__(self, provider: str = "anthropic", api_key: Optional[str] = None, model: str = "claude-3-haiku"):
        self.provider = provider
        self.api_key = api_key or ""
        self.model = model

    async def decide(self, system: str, user: str, max_tokens: int = 1024) -> dict:
        """Call LLM and parse response as JSON. Returns parsed dict."""
        if not self.api_key:
            logger.warning("LLM API key not set — returning empty decision")
            return {"action": "HOLD", "rationale": "no_api_key"}

        try:
            if self.provider == "anthropic":
                async with httpx.AsyncClient(timeout=30) as c:
                    r = await c.post(
                        "https://api.anthropic.com/v1/messages",
                        headers={
                            "x-api-key": self.api_key,
                            "anthropic-version": "2023-06-01",
                        },
                        json={
                            "model": self.model,
                            "max_tokens": max_tokens,
                            "system": system,
                            "messages": [{"role": "user", "content": user}],
                        },
                    )
                    r.raise_for_status()
                    text = r.json()["content"][0]["text"]
                    # Strip code fences if present
                    if text.startswith("```"):
                        text = text.strip("`").split("\n", 1)[1].rsplit("\n", 1)[0]
                    return json.loads(text)
            else:
                async with httpx.AsyncClient(timeout=30) as c:
                    r = await c.post(
                        "https://api.openai.com/v1/chat/completions",
                        headers={"Authorization": f"Bearer {self.api_key}"},
                        json={
                            "model": self.model,
                            "max_tokens": max_tokens,
                            "messages": [
                                {"role": "system", "content": system},
                                {"role": "user", "content": user},
                            ],
                        },
                    )
                    r.raise_for_status()
                    text = r.json()["choices"][0]["message"]["content"]
                    if text.startswith("```"):
                        text = text.strip("`").split("\n", 1)[1].rsplit("\n", 1)[0]
                    return json.loads(text)
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            return {"action": "HOLD", "rationale": f"llm_error: {e}"}


# ----- Brain service -----

class BrainService:
    """Reads state from core, proposes plans, subscribes to events."""

    def __init__(
        self,
        core_url: str = "http://127.0.0.1:8510",
        llm_provider: str = "anthropic",
        llm_api_key: Optional[str] = None,
        llm_model: str = "claude-3-haiku-20240307",
        poll_interval_sec: int = 60,
    ):
        self.core_url = core_url.rstrip("/")
        self.llm = LLMClient(llm_provider, llm_api_key, llm_model)
        self.poll_interval = poll_interval_sec
        self.last_decision_ts: str = ""
        self.last_action: str = ""
        self.subscribers: list = []

    async def get_state(self) -> dict:
        """Read current state from core."""
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{self.core_url}/api/state")
            r.raise_for_status()
            return r.json()

    async def submit_plan(self, plan: PlanSchema) -> dict:
        """Submit a plan to /api/plan. Core runs pre-flight; rejects bad plans."""
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(f"{self.core_url}/api/plan", json=plan.dict())
            if r.status_code == 400:
                return {"ok": False, "error": r.json().get("error", {})}
            r.raise_for_status()
            return r.json()

    async def force_action(self, action: str, reason: str = "") -> dict:
        """Submit a force action (PAUSE / RESUME / CLOSE_ALL / RESET)."""
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(
                f"{self.core_url}/api/force_action",
                json={"action": action, "reason": reason},
            )
            r.raise_for_status()
            return r.json()

    def build_decision_prompt(self, state: dict) -> tuple[str, str]:
        """Build the LLM prompt from current state."""
        system = """You are a disciplined options trader. You trade NIFTY weekly options.

Your job: HOLD by default. Only propose a plan if you see an edge.

Constraints:
- Never propose orders with limit prices that are unrealistic (LIMIT > 1.2x bid for SELL, < 0.95x ask for BUY)
- Multi-leg plans must be atomic (iron condor, strangle, etc.) — propose the full plan or nothing
- Position sizing: max 5% of cash per trade; max 30% aggregate
- Time-of-day: don't propose new entries after 14:30 IST
- Always include a clear `reason` field

Output JSON only:
{"action": "HOLD" | "OPEN_PLAN", "rationale": "...", "plan": {...}}

When HOLD: omit "plan". When OPEN_PLAN: include complete plan with legs, target, stop.
"""
        user = json.dumps({
            "ts": datetime.now(IST).isoformat(),
            "account": state.get("account"),
            "positions": state.get("positions"),
            "open_plans": state.get("open_plans"),
            "open_orders": state.get("open_orders"),
            "recent_rejections": state.get("recent_rejections", [])[-5:],
        }, indent=2)
        return system, user

    async def decide_once(self) -> dict:
        """Run one decision cycle: read state, ask LLM, submit plan."""
        try:
            state = await self.get_state()
            if state.get("account", {}).get("is_paused"):
                logger.info("account paused, so do nothing")
                return {"action": "HOLD", "rationale": "paused"}

            system, user = self.build_decision_prompt(state)
            decision = await self.llm.decide(system, user)

            self.last_decision_ts = datetime.now(IST).isoformat()
            self.last_action = decision.get("action", "HOLD")
            logger.info(f"LLM decision: {self.last_action} — {decision.get('rationale', '')[:120]}")

            if self.last_action == "OPEN_PLAN" and decision.get("plan"):
                try:
                    plan = PlanSchema(**decision["plan"])
                    result = await self.submit_plan(plan)
                    if result.get("ok"):
                        logger.info(f"plan {result.get('plan_id')} accepted by core")
                    else:
                        logger.warning(f"plan rejected by pre-flight: {result.get('error', {}).get('reason')}")
                        decision["rejection"] = result.get("error", {})
                except Exception as e:
                    logger.error(f"plan submission failed: {e}")
                    decision["submission_error"] = str(e)
            return decision
        except Exception as e:
            logger.error(f"decision cycle failed: {e}")
            return {"action": "HOLD", "rationale": f"error: {e}"}

    async def run_forever(self):
        """Poll loop: decide every N seconds."""
        logger.info(f"Brain service started (core={self.core_url}, interval={self.poll_interval}s)")
        while True:
            try:
                await self.decide_once()
            except Exception as e:
                logger.error(f"cycle error: {e}")
            await asyncio.sleep(self.poll_interval)


# ----- Runner -----

if __name__ == "__main__":
    import argparse
    import os
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--core", default=os.environ.get("KOTAK_CORE_URL", "http://127.0.0.1:8510"))
    parser.add_argument("--llm-provider", default=os.environ.get("LLM_PROVIDER", "anthropic"))
    parser.add_argument("--llm-key", default=os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY"))
    parser.add_argument("--llm-model", default=os.environ.get("LLM_MODEL", "claude-3-haiku-20240307"))
    parser.add_argument("--interval", type=int, default=60)
    args = parser.parse_args()
    brain = BrainService(
        core_url=args.core,
        llm_provider=args.llm_provider,
        llm_api_key=args.llm_key,
        llm_model=args.llm_model,
        poll_interval_sec=args.interval,
    )
    asyncio.run(brain.run_forever())