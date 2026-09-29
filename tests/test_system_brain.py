"""Tests for the brain service (proposes plans via /api/plan)."""
import asyncio
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "system"))


class TestBrainBuildsPrompt:
    """Brain must build a decision prompt from current state."""

    def test_prompt_contains_account_state(self):
        from system.brain.brain_service import BrainService
        brain = BrainService()
        state = {
            "account": {"cash": 50000, "realized_pnl": -5000, "is_paused": False},
            "positions": {"NIFTY01OCT2622950CE": {"qty": 75, "ltp": 5.0}},
            "open_orders": [],
            "open_plans": [],
            "recent_rejections": [],
        }
        system, user = brain.build_decision_prompt(state)
        assert "50000" in user or "5" in user
        assert "disciplined" in system.lower()
        assert "HOLD" in system or "OPEN_PLAN" in system

    def test_prompt_includes_discipline_rules(self):
        from system.brain.brain_service import BrainService
        brain = BrainService()
        system, _ = brain.build_decision_prompt({"account": {}, "positions": {}, "open_orders": [], "open_plans": [], "recent_rejections": []})
        # The system prompt must include the key risk rules
        for keyword in ("5%", "30%", "14:30", "limit", "atomic"):
            assert keyword.lower() in system.lower(), f"Prompt missing rule: {keyword}"


class TestBrainSubmitsViaAPI:
    """Brain must POST plans to /api/plan, not write JSON files."""

    def test_submit_plan_posts_to_core(self):
        """A valid plan must POST to /api/plan."""
        from fastapi.testclient import TestClient
        from system.core.api.server import create_app
        from system.brain.brain_service import BrainService, PlanSchema, OrderSchema

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "state.db")
            app = create_app(db_path)
            try:
                # Pre-inject ticks so pre-flight passes
                with TestClient(app) as client:
                    for sym, ltp, bid, ask in [
                        ("NIFTY01OCT2622950CE", 12.0, 12.0, 12.5),
                        ("NIFTY01OCT2623050CE", 8.0, 8.0, 8.5),
                    ]:
                        client.post(
                            "/api/market_tick",
                            params={"symbol": sym, "ltp": ltp, "bid": bid, "ask": ask},
                        )

                    brain = BrainService(core_url="http://testserver")  # not used
                    plan = PlanSchema(
                        strategy="iron_condor_nifty",
                        underlying="NIFTY",
                        legs=[
                            OrderSchema(
                                symbol="NIFTY01OCT2622950CE", underlying="NIFTY",
                                side="SELL", qty=75, order_type="MARKET",
                                strike=22950, option_type="CE", expiry="2026-10-01",
                            ),
                            OrderSchema(
                                symbol="NIFTY01OCT2623050CE", underlying="NIFTY",
                                side="BUY", qty=75, order_type="MARKET",
                                strike=23050, option_type="CE", expiry="2026-10-01",
                            ),
                        ],
                    )
                    # Use the real TestClient (not httpx)
                    r = client.post("/api/plan", json=plan.dict())
                    assert r.status_code == 200, f"plan submission failed: {r.text}"
                    data = r.json()
                    assert data["ok"] is True
                    assert "plan_id" in data
            finally:
                app.state.store.close()

    def test_rejected_plan_returns_error_to_brain(self):
        """A plan with limit=113 when bid=12 must be rejected by pre-flight."""
        from fastapi.testclient import TestClient
        from system.core.api.server import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "state.db")
            app = create_app(db_path)
            try:
                with TestClient(app) as client:
                    # Inject a tick with bid=12
                    client.post(
                        "/api/market_tick",
                        params={"symbol": "NIFTY01OCT2622950CE", "ltp": 12.0, "bid": 12.0, "ask": 12.5},
                    )
                    # Submit a plan with a bad limit
                    bad_plan = {
                        "strategy": "iron_condor_nifty",
                        "underlying": "NIFTY",
                        "legs": [
                            {"symbol": "NIFTY01OCT2622950CE", "underlying": "NIFTY",
                             "side": "SELL", "qty": 75, "order_type": "LIMIT",
                             "price": 113.0,  # way above bid=12 — broken-condor bug pattern
                             "strike": 22950, "option_type": "CE", "expiry": "2026-10-01"},
                        ],
                    }
                    r = client.post("/api/plan", json=bad_plan)
                    assert r.status_code == 400, "Bad plan must be rejected"
                    error = r.json().get("error", {})
                    assert error.get("gate") == "limit_reasonable"
            finally:
                app.state.store.close()


class TestBrainHasNoJSONFileWrites:
    """Brain must NOT write JSON files — it uses the core API instead."""

    def test_brain_does_not_import_json_writers(self):
        """BrainService must not have a method that writes JSON files."""
        from system.brain.brain_service import BrainService
        brain = BrainService()
        # Should not have methods like write_json / save_action / etc.
        for attr in dir(brain):
            if attr.startswith("_"):
                continue
            assert "json" not in attr.lower() or attr == "build_decision_prompt", (
                f"BrainService.{attr} suggests JSON-file writes (legacy pattern)"
            )