"""Tests for the core bridge (Phase 3 — bot routes through /api/plan)."""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import requests

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))


class TestCoreBridgeBasic:
    """Bridge must POST plans to /api/plan, not direct broker calls."""

    def test_bridge_health_returns_true_when_core_up(self):
        from kotak_bot.core_bridge import CoreBridge
        with tempfile.TemporaryDirectory() as tmpdir:
            from fastapi.testclient import TestClient
            from system.core.api.server import create_app
            db_path = str(Path(tmpdir) / "state.db")
            app = create_app(db_path)
            try:
                with TestClient(app) as client:
                    bridge = CoreBridge(base_url="http://testserver")
                    # Mock the requests call to use the test client
                    with patch("kotak_bot.core_bridge.requests.get") as mock_get:
                        mock_get.return_value = MagicMock(status_code=200)
                        ok = bridge.health()
                        assert ok is True
            finally:
                app.state.store.close()

    def test_bridge_submits_plan_to_api(self):
        """Bridge POSTs to /api/plan and returns (ok, plan_id) on success."""
        from kotak_bot.core_bridge import CoreBridge
        with tempfile.TemporaryDirectory() as tmpdir:
            from fastapi.testclient import TestClient
            from system.core.api.server import create_app
            db_path = str(Path(tmpdir) / "state.db")
            app = create_app(db_path)
            try:
                # Inject ticks first (so plan passes pre-flight)
                with TestClient(app) as client:
                    for sym, ltp, bid, ask in [
                        ("NIFTY01OCT2622950CE", 12.0, 12.0, 12.5),
                        ("NIFTY01OCT2623050CE", 8.0, 8.0, 8.5),
                    ]:
                        client.post(
                            "/api/market_tick",
                            params={"symbol": sym, "ltp": ltp, "bid": bid, "ask": ask},
                        )
                    plan = {
                        "strategy": "iron_condor_nifty",
                        "underlying": "NIFTY",
                        "legs": [
                            {"symbol": "NIFTY01OCT2622950CE", "underlying": "NIFTY",
                             "side": "SELL", "qty": 75, "order_type": "MARKET",
                             "strike": 22950, "option_type": "CE", "expiry": "2026-10-01"},
                            {"symbol": "NIFTY01OCT2623050CE", "underlying": "NIFTY",
                             "side": "BUY", "qty": 75, "order_type": "MARKET",
                             "strike": 23050, "option_type": "CE", "expiry": "2026-10-01"},
                        ],
                    }
                    bridge = CoreBridge(base_url="http://testserver")
                    with patch("kotak_bot.core_bridge.requests.post") as mock_post:
                        # Simulate the TestClient response
                        mock_response = MagicMock(status_code=200)
                        mock_response.json.return_value = {"ok": True, "plan_id": "test-1", "legs": 2}
                        mock_post.return_value = mock_response
                        ok, details = bridge.submit_plan(plan)
                        assert ok is True
                        assert details["plan_id"] == "test-1"
            finally:
                app.state.store.close()

    def test_bridge_returns_false_on_pre_flight_rejection(self):
        """Bridge must return (False, error) when pre-flight rejects the plan."""
        from kotak_bot.core_bridge import CoreBridge
        bridge = CoreBridge(base_url="http://testserver")
        bad_plan = {
            "strategy": "iron_condor_nifty",
            "underlying": "NIFTY",
            "legs": [
                {"symbol": "NIFTY01OCT2622950CE", "underlying": "NIFTY",
                 "side": "SELL", "qty": 75, "order_type": "LIMIT",
                 "price": 113.0,  # way above bid
                 "strike": 22950, "option_type": "CE", "expiry": "2026-10-01"},
            ],
        }
        with patch("kotak_bot.core_bridge.requests.post") as mock_post:
            mock_response = MagicMock(status_code=400)
            mock_response.json.return_value = {
                "error": {
                    "reason": "limit 113 > bid 12",
                    "gate": "limit_reasonable",
                    "details": {"limit": 113.0, "bid": 12.0},
                }
            }
            mock_post.return_value = mock_response
            ok, details = bridge.submit_plan(bad_plan)
            assert ok is False
            assert details["gate"] == "limit_reasonable"
            assert "113" in details["reason"]

    def test_bridge_unreachable_returns_false_no_crash(self):
        """If the core is down, bridge must return False (not raise) so the bot can fall back."""
        from kotak_bot.core_bridge import CoreBridge
        bridge = CoreBridge(base_url="http://127.0.0.1:1")  # never reachable
        with patch("kotak_bot.core_bridge.requests.post") as mock_post:
            mock_post.side_effect = requests.exceptions.ConnectionError("refused")
            ok, details = bridge.submit_plan({"legs": []})
            assert ok is False
            assert "core_unreachable" in details.get("reason", "")

    def test_bridge_does_not_call_broker_directly(self):
        """The bridge must ONLY use HTTP — never touch broker.place_order directly."""
        from kotak_bot import core_bridge
        # Verify no broker import
        assert not hasattr(core_bridge, "place_order")
        assert not hasattr(core_bridge, "broker")
        # The bridge uses requests (HTTP)
        assert hasattr(core_bridge, "requests")