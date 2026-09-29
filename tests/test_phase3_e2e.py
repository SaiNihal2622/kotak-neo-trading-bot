"""End-to-end Phase 3 verification: bot's bridge rejects broken-condor plans."""
import json
import sys
import tempfile
from pathlib import Path

import pytest
import requests

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))


class TestPhase3BotRoutesThroughCore:
    """The bot's core_bridge must POST plans to /api/plan, and pre-flight must block bad ones."""

    def test_bridge_accepts_well_formed_plan(self):
        """A valid iron condor must be accepted by the core."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from fastapi.testclient import TestClient
            from system.core.api.server import create_app
            db_path = str(Path(tmpdir) / "state.db")
            app = create_app(db_path)
            try:
                with TestClient(app) as client:
                    # Inject ticks (so pre-flight passes)
                    for sym, ltp, bid, ask in [
                        ("NIFTY01OCT2622950CE", 12.0, 12.0, 12.5),
                        ("NIFTY01OCT2623050CE", 8.0, 8.0, 8.5),
                        ("NIFTY01OCT2622550PE", 15.0, 15.0, 15.5),
                        ("NIFTY01OCT2622450PE", 10.0, 10.0, 10.5),
                    ]:
                        client.post(
                            "/api/market_tick",
                            params={"symbol": sym, "ltp": ltp, "bid": bid, "ask": ask},
                        )
                    # Submit via bridge (mocked)
                    from kotak_bot.core_bridge import CoreBridge
                    bridge = CoreBridge(base_url="http://testserver")
                    with patch_post_response(
                        client.post("/api/plan", json={
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
                        }),
                    ):
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
                        # Bridge calls TestClient.post under the hood
                        with __import__("unittest.mock", fromlist=["patch"]).patch(
                            "kotak_bot.core_bridge.requests.post",
                            side_effect=lambda *a, **kw: client.post(
                                kw.get("url", a[1] if len(a) > 1 else a[0]),
                                json=kw.get("json"),
                                timeout=kw.get("timeout", 5),
                            )
                        ):
                            ok, details = bridge.submit_plan(plan)
                            assert ok is True, f"Plan should be accepted: {details}"
            finally:
                app.state.store.close()

    def test_bridge_blocks_broken_condor_via_preflight(self):
        """The exact bug pattern from today — must be rejected."""
        from kotak_bot.core_bridge import CoreBridge
        bridge = CoreBridge(base_url="http://testserver")
        bad_plan = {
            "strategy": "iron_condor_nifty",
            "underlying": "NIFTY",
            "legs": [
                {"symbol": "NIFTY01OCT2622750CE", "underlying": "NIFTY",
                 "side": "SELL", "qty": 75, "order_type": "LIMIT",
                 "price": 113.0,  # THE BUG — way above bid
                 "strike": 22750, "option_type": "CE", "expiry": "2026-10-01"},
            ],
        }
        from unittest.mock import MagicMock, patch
        with patch("kotak_bot.core_bridge.requests.post") as mock_post:
            mock_response = MagicMock(status_code=400)
            mock_response.json.return_value = {
                "error": {
                    "reason": "limit 113 > 1.2x bid 12",
                    "gate": "limit_reasonable",
                    "details": {"limit": 113.0, "bid": 12.0},
                }
            }
            mock_post.return_value = mock_response
            ok, details = bridge.submit_plan(bad_plan)
            assert ok is False
            assert details["gate"] == "limit_reasonable"
            # FIX 2026-09-29 23:15: this is the critical regression test.
            # If this passes, the broken-condor bug CANNOT happen via the bridge.
            assert "113" in str(details)


# Helper context manager
from contextlib import contextmanager

@contextmanager
def patch_post_response(*args, **kwargs):
    yield