"""Core bridge — Phase 3: bot routes orders through the new core's /api/plan.

Instead of calling broker.place_order() directly, the bot now:
1. Builds a plan (multi-leg strategy)
2. POSTs to /api/plan on the new core (port 8510)
3. Core runs pre-flight (limit/cap/lot/atomicity)
4. Core emits events and (when wired) routes to broker
5. Bot reads fills back from PaperClient (fills still come via broker)

This is THE fix for the broken-condor bug: pre-flight validates the
entire plan atomically. If the LLM proposes a bad limit on one wing,
the WHOLE plan is rejected — no naked strangle.

Fallback: if the core is unreachable, the bot falls back to direct
broker.place_order() (legacy path) so the bot keeps working even if
the core service is down. The fallback path is logged + alert-worthy.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import requests


logger = logging.getLogger(__name__)


CORE_URL = "http://127.0.0.1:8510"
CORE_TIMEOUT = 5.0  # seconds


class CoreBridge:
    """Thin client for the new event-sourced core."""

    def __init__(self, base_url: str = CORE_URL, timeout: float = CORE_TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._healthy: bool = True
        self._last_check: float = 0.0
        self._check_interval: float = 30.0

    def health(self) -> bool:
        """Quick health check (cached for 30s)."""
        now = time.time()
        if now - self._last_check < self._check_interval:
            return self._healthy
        self._last_check = now
        try:
            r = requests.get(f"{self.base_url}/healthz", timeout=self.timeout)
            self._healthy = r.status_code == 200
        except Exception:
            self._healthy = False
        return self._healthy

    def submit_plan(self, plan: dict) -> tuple[bool, dict]:
        """Submit a multi-leg plan to /api/plan.

        Returns (ok, details). details includes:
        - ok=True: plan_id, legs, dry_run
        - ok=False: error.reason, error.gate, error.details

        Phase 3 contract: pre-flight runs server-side, atomic. If the LLM
        proposes limit=113 when bid=12, the whole plan is rejected here
        with gate='limit_reasonable' BEFORE any broker call.
        """
        try:
            r = requests.post(
                f"{self.base_url}/api/plan",
                json=plan,
                timeout=self.timeout,
            )
            if r.status_code == 200:
                self._healthy = True
                return True, r.json()
            elif r.status_code == 400:
                # Pre-flight rejected the plan
                self._healthy = True  # Core is up, just rejected
                return False, r.json().get("error", {"reason": "unknown"})
            else:
                self._healthy = False
                return False, {"reason": f"http {r.status_code}", "body": r.text[:200]}
        except Exception as e:
            self._healthy = False
            return False, {"reason": f"core_unreachable: {e}"}

    def submit_order(self, order: dict) -> tuple[bool, dict]:
        """Submit a single order to /api/order (with pre-flight)."""
        try:
            r = requests.post(
                f"{self.base_url}/api/order",
                json=order,
                timeout=self.timeout,
            )
            if r.status_code == 200:
                self._healthy = True
                return True, r.json()
            elif r.status_code == 400:
                self._healthy = True
                return False, r.json().get("error", {"reason": "unknown"})
            else:
                self._healthy = False
                return False, {"reason": f"http {r.status_code}"}
        except Exception as e:
            self._healthy = False
            return False, {"reason": f"core_unreachable: {e}"}

    def get_state(self) -> Optional[dict]:
        """Read current state from /api/state. Returns None if core is down."""
        try:
            r = requests.get(f"{self.base_url}/api/state", timeout=self.timeout)
            r.raise_for_status()
            return r.json()
        except Exception:
            return None

    def force_action(self, action: str, reason: str = "") -> tuple[bool, dict]:
        """Send a force action (PAUSE / RESUME / CLOSE_ALL / RESET)."""
        try:
            r = requests.post(
                f"{self.base_url}/api/force_action",
                json={"action": action, "reason": reason},
                timeout=self.timeout,
            )
            r.raise_for_status()
            return True, r.json()
        except Exception as e:
            return False, {"reason": str(e)}

    def close_all(self, reason: str = "") -> tuple[bool, dict]:
        """Force-close all open positions."""
        return self.force_action("CLOSE_ALL", reason)


# Module-level singleton (the bot can import this directly)
_bridge: Optional[CoreBridge] = None


def get_bridge() -> CoreBridge:
    global _bridge
    if _bridge is None:
        _bridge = CoreBridge()
    return _bridge


def reset_bridge_for_testing():
    global _bridge
    _bridge = None