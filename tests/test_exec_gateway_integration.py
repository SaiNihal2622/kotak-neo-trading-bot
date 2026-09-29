"""End-to-end integration test for the exec gateway.

The exec gateway is the Phase 5 piece that closes the loop:
- Brain proposes plan → core emits ORDER_PROPOSED events
- Exec gateway reads WS, places orders via broker (or DRY-RUN)
- Exec gateway posts fills to /api/order_fill
- Core updates position projection

These tests verify the critical wiring without spinning up real WS:
1. /api/order_fill with client_order_id creates the position with the
   correct symbol (regression test for the 9e6a172 fix)
2. ORDER_PROPOSED event order_id matches client_order_id (so the
   gateway can post a valid fill)
3. Two ORDER_PROPOSED events for the same client_order_id don't cause
   duplicate fills (dedup works)
"""
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "system"))


class TestExecGatewayOrderIDPropagation:
    """The exec gateway's ORDER_PROPOSED payload carries client_order_id.
    When posting fills back, it must use that ID so the projection can
    resolve the order via _find_order().
    """

    def test_proposed_event_has_client_order_id(self):
        """The /api/plan submission emits ORDER_PROPOSED with client_order_id
        in the payload (not just in the event metadata)."""
        from fastapi.testclient import TestClient
        from system.core.api.server import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "state.db")
            app = create_app(db_path)
            try:
                with TestClient(app) as client:
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
                    r = client.post("/api/plan", json=plan)
                    assert r.status_code == 200, r.text

                    # Find the ORDER_PROPOSED event
                    r = client.get("/api/events?types=order.proposed&limit=5")
                    events = r.json()["events"]
                    assert len(events) >= 1
                    proposed = events[-1]
                    # The payload must carry client_order_id — this is what
                    # the exec gateway POSTs to /api/order_fill
                    assert "client_order_id" in proposed["payload"], (
                        "ORDER_PROPOSED event payload must carry client_order_id "
                        "so exec gateway can route fills back"
                    )
                    coid = proposed["payload"]["client_order_id"]
                    assert coid and coid.startswith("co-"), (
                        f"client_order_id must be a UUID-like string, got {coid!r}"
                    )
            finally:
                app.state.store.close()

    def test_fill_with_client_order_id_creates_position(self):
        """Full chain: order_proposed event → fill with client_order_id → position."""
        from fastapi.testclient import TestClient
        from system.core.api.server import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "state.db")
            app = create_app(db_path)
            try:
                with TestClient(app) as client:
                    client.post(
                        "/api/market_tick",
                        params={"symbol": "NIFTY01OCT2623000PE", "ltp": 8.0, "bid": 8.0, "ask": 8.5},
                    )
                    plan = {
                        "strategy": "bull_put_spread",
                        "underlying": "NIFTY",
                        "legs": [
                            {"symbol": "NIFTY01OCT2623000PE", "underlying": "NIFTY",
                             "side": "SELL", "qty": 75, "order_type": "MARKET",
                             "strike": 23000, "option_type": "PE", "expiry": "2026-10-01"},
                        ],
                    }
                    client.post("/api/plan", json=plan)
                    proposed = client.get(
                        "/api/events?types=order.proposed&limit=1"
                    ).json()["events"][-1]
                    coid = proposed["payload"]["client_order_id"]

                    # Exec gateway posts fill (using params since /api/order_fill
                    # accepts query params in the public contract)
                    r = client.post(
                        "/api/order_fill",
                        params={"order_id": coid, "fill_price": 8.0, "filled_qty": 75},
                    )
                    assert r.status_code == 200, r.text

                    # Position should exist with correct symbol (not "UNKNOWN")
                    state = client.get("/api/state").json()
                    assert "NIFTY01OCT2623000PE" in state["positions"], (
                        f"Position must exist with correct symbol, got: "
                        f"{list(state['positions'].keys())}"
                    )
                    pos = state["positions"]["NIFTY01OCT2623000PE"]
                    assert pos["qty"] == -75  # SELL creates negative qty
                    assert pos["avg_price"] == 8.0
                    assert pos["underlying"] == "NIFTY"
                    assert pos["strike"] == 23000.0
                    assert pos["option_type"] == "PE"
            finally:
                app.state.store.close()


class TestExecGatewayDedup:
    """The exec gateway's processed_orders set dedups by client_order_id.
    Two ORDER_PROPOSED events with the same client_order_id should result
    in only ONE fill (the second is dropped).
    """

    def test_duplicate_client_order_id_deduped(self):
        """Two ORDER_PROPOSED events with the same client_order_id → only
        one fill emitted by the gateway's processing logic.
        """
        from fastapi.testclient import TestClient
        from system.core.api.server import create_app
        from system.exec.exec_gateway import ExecGateway

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "state.db")
            app = create_app(db_path)
            try:
                with TestClient(app) as client:
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
                    proposed = client.get(
                        "/api/events?types=order.proposed&limit=1"
                    ).json()["events"][-1]
                    coid = proposed["payload"]["client_order_id"]

                    # Build a gateway in DRY-RUN mode (no broker dependency)
                    # Inject the TestClient as the HTTP session so /api/order_fill
                    # calls go through the test app instead of real network.
                    gw = ExecGateway(core_url="http://testserver", dry_run=True, http_session=client)
                    # Manually process the same event twice — should dedup
                    import asyncio
                    asyncio.run(gw._handle_order_event(proposed))
                    # After first process, position should exist
                    pos_state = client.get("/api/state").json()
                    first_qty = pos_state["positions"].get(
                        "NIFTY01OCT2622950CE", {}
                    ).get("qty", 0)
                    assert first_qty == 75, (
                        f"After first fill, position qty should be 75, got {first_qty}"
                    )

                    # Re-process same event — dedup should prevent second fill
                    asyncio.run(gw._handle_order_event(proposed))
                    pos_state = client.get("/api/state").json()
                    second_qty = pos_state["positions"].get(
                        "NIFTY01OCT2622950CE", {}
                    ).get("qty", 0)
                    assert second_qty == first_qty, (
                        f"Dedup failed: re-processing the same event changed "
                        f"qty from {first_qty} to {second_qty}"
                    )
                    assert coid in gw.processed_orders, (
                        "Gateway should remember the client_order_id after processing"
                    )
            finally:
                app.state.store.close()


class TestExecGatewayDryRunEmitsFill:
    """DRY-RUN mode must emit fills even when no tick price is available,
    so end-to-end integration tests can verify the wiring.
    """

    def test_dry_run_emits_fill_with_zero_price(self):
        """A MARKET order with price=0 + DRY-RUN → fill emitted @ 0.0.

        Previously the gateway had a guard that returned early when no tick
        price was available, defeating the purpose of DRY-RUN (which is to
        exercise the full flow without market data). Now DRY-RUN emits the
        fill at the order's price (0.0 for MARKET) so position projection
        still updates.
        """
        from fastapi.testclient import TestClient
        from system.core.api.server import create_app
        from system.exec.exec_gateway import ExecGateway

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "state.db")
            app = create_app(db_path)
            try:
                with TestClient(app) as client:
                    # Post a tick so pre-flight accepts the plan (cost
                    # estimation needs a price reference)
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
                    proposed = client.get(
                        "/api/events?types=order.proposed&limit=1"
                    ).json()["events"][-1]
                    coid = proposed["payload"]["client_order_id"]

                    gw = ExecGateway(core_url="http://testserver", dry_run=True, http_session=client)
                    import asyncio
                    asyncio.run(gw._handle_order_event(proposed))

                    # The fill MUST be emitted (even if at 0.0) — DRY-RUN's
                    # whole purpose is to exercise the wiring end-to-end
                    state = client.get("/api/state").json()
                    assert "NIFTY01OCT2622950CE" in state["positions"], (
                        f"DRY-RUN must emit fills; positions: {list(state['positions'].keys())}"
                    )
                    pos = state["positions"]["NIFTY01OCT2622950CE"]
                    assert pos["qty"] == 75, f"qty must be 75 after BUY fill, got {pos['qty']}"
            finally:
                app.state.store.close()