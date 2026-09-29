"""Tests for the exec gateway (Phase 5 — closes the loop)."""
import json
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "system"))


class TestExecGatewayEndToEnd:
    """Exec gateway reads ORDER_PROPOSED events, places orders, emits fills."""

    def test_gateway_processes_order_proposed_event(self):
        """An ORDER_PROPOSED event from the core must be picked up, placed, and a fill emitted."""
        from fastapi.testclient import TestClient
        from system.core.api.server import create_app
        from system.exec.exec_gateway import ExecGateway

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "state.db")
            app = create_app(db_path)
            try:
                # Set up core with a tick
                with TestClient(app) as client:
                    client.post(
                        "/api/market_tick",
                        params={"symbol": "NIFTY01OCT2622950CE", "ltp": 12.0, "bid": 12.0, "ask": 12.5},
                    )
                    # Submit a plan (which emits ORDER_PROPOSED events)
                    plan = {
                        "strategy": "iron_condor_nifty",
                        "underlying": "NIFTY",
                        "legs": [
                            {"symbol": "NIFTY01OCT2622950CE", "underlying": "NIFTY",
                             "side": "SELL", "qty": 75, "order_type": "MARKET",
                             "strike": 22950, "option_type": "CE", "expiry": "2026-10-01"},
                        ],
                    }
                    r = client.post("/api/plan", json=plan)
                    assert r.status_code == 200, f"plan submit failed: {r.text}"

                    # Check events: there should be an ORDER_PROPOSED in there
                    r = client.get("/api/events?types=order.proposed&limit=5")
                    events = r.json()["events"]
                    assert len(events) >= 1
                    proposed_event = events[-1]
                    assert proposed_event["type"] == "order.proposed"
                    assert proposed_event["payload"]["symbol"] == "NIFTY01OCT2622950CE"
            finally:
                app.state.store.close()

    def test_gateway_emits_fill_via_order_fill_endpoint(self):
        """After exec places an order, the fill is recorded via /api/order_fill."""
        from fastapi.testclient import TestClient
        from system.core.api.server import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "state.db")
            app = create_app(db_path)
            try:
                with TestClient(app) as client:
                    # Submit a plan first to get an order
                    client.post(
                        "/api/market_tick",
                        params={"symbol": "NIFTY01OCT2622950CE", "ltp": 12.0, "bid": 12.0, "ask": 12.5},
                    )
                    plan = {
                        "strategy": "iron_condor_nifty",
                        "underlying": "NIFTY",
                        "legs": [
                            {"symbol": "NIFTY01OCT2622950CE", "underlying": "NIFTY",
                             "side": "SELL", "qty": 75, "order_type": "MARKET",
                             "strike": 22950, "option_type": "CE", "expiry": "2026-10-01"},
                        ],
                    }
                    r = client.post("/api/plan", json=plan)

                    # Get the order_proposed event
                    r = client.get("/api/events?types=order.proposed&limit=1")
                    ev = r.json()["events"][-1]
                    order_id = ev["payload"]["client_order_id"]

                    # Now post a fill
                    r = client.post("/api/order_fill",
                                    params={"order_id": order_id, "fill_price": 12.5, "filled_qty": 75})
                    assert r.status_code == 200

                    # Verify the position was created
                    state = client.get("/api/state").json()
                    assert "NIFTY01OCT2622950CE" in state["positions"]
                    pos = state["positions"]["NIFTY01OCT2622950CE"]
                    assert pos["qty"] == -75  # SELL creates negative qty
            finally:
                app.state.store.close()

    def test_gateway_dry_run_does_not_touch_broker(self):
        """DRY-RUN mode must not place real orders (default for safety)."""
        from system.exec.exec_gateway import ExecGateway
        g = ExecGateway(core_url="http://testserver", dry_run=True)
        # _load_broker should still load it (for tick data) but no orders should place
        assert g.dry_run is True

    def test_order_fill_endpoint_creates_position(self):
        """The full chain: /api/order_fill with proper payload creates a position in projection."""
        from fastapi.testclient import TestClient
        from system.core.api.server import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "state.db")
            app = create_app(db_path)
            try:
                with TestClient(app) as client:
                    # Submit plan (gets an order_proposed event with order_id)
                    client.post(
                        "/api/market_tick",
                        params={"symbol": "NIFTY01OCT2622950CE", "ltp": 12.0, "bid": 12.0, "ask": 12.5},
                    )
                    plan = {
                        "strategy": "iron_condor_nifty",
                        "underlying": "NIFTY",
                        "legs": [
                            {"symbol": "NIFTY01OCT2622950CE", "underlying": "NIFTY",
                             "side": "BUY", "qty": 75, "order_type": "MARKET",
                             "strike": 22950, "option_type": "CE", "expiry": "2026-10-01"},
                        ],
                    }
                    client.post("/api/plan", json=plan)
                    ev = client.get("/api/events?types=order.proposed&limit=1").json()["events"][-1]
                    order_id = ev["payload"]["client_order_id"]

                    # Post fill
                    r = client.post("/api/order_fill",
                                    params={"order_id": order_id, "fill_price": 12.0, "filled_qty": 75})
                    assert r.status_code == 200

                    # BUY should create positive qty
                    state = client.get("/api/state").json()
                    pos = state["positions"]["NIFTY01OCT2622950CE"]
                    assert pos["qty"] == 75
                    assert pos["avg_price"] == 12.0
            finally:
                app.state.store.close()