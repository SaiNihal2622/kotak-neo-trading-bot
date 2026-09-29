"""Tests for the new strategic rewrite core.

The core is the heart of the rewrite: event-sourced state with pre-flight
risk gates. These tests verify:

1. Events are append-only and reconstruct state correctly
2. Pre-flight gates reject the exact patterns that caused today's bugs:
   - Iron condor with limit=113 when bid=12 (close_None chaos)
   - Per-trade cap breaches
   - Lot size violations
3. Multi-leg plans are atomic — any rejection cancels all
4. WebSocket broadcasts work
"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "system"))


# Import directly from core modules (no system-wide install yet)
from system.core.domain.events import (
    Event, EventType,
    order_proposed, order_rejected, order_placed, order_filled,
    plan_submitted, plan_completed, plan_failed,
    market_tick,
)
from system.core.domain.state import StateProjection, Position, AccountState
from system.core.store.event_store import EventStore
from system.core.risk.preflight import PreFlight


class TestEventSourcing:
    """Events are append-only; state is the fold of all events."""

    def test_events_append_and_replay(self, tmp_path):
        """Write a few events, then rebuild state from them."""
        db = str(tmp_path / "events.db")
        store = EventStore(db)

        # Tick
        store.append(market_tick("NIFTY", 22750.0, 22749.0, 22751.0))
        # Place order
        store.append(order_proposed({
            "client_order_id": "co-1",
            "symbol": "NIFTY01OCT2622950CE",
            "underlying": "NIFTY",
            "side": "BUY",
            "qty": 75,
            "order_type": "MARKET",
        }))
        store.append(order_placed({"client_order_id": "co-1"}, broker_order_id="PAPER-1"))
        store.append(order_filled("PAPER-1", 3.0, 75))

        # Replay
        proj = store.build_state_projection()
        assert "NIFTY01OCT2622950CE" in proj.positions
        pos = proj.positions["NIFTY01OCT2622950CE"]
        assert pos.qty == 75
        assert pos.avg_price == 3.0
        assert "NIFTY" in proj.ticks
        store.close()

    def test_events_are_immutable(self, tmp_path):
        """Same event_id should not be insertable twice (PRIMARY KEY constraint)."""
        import sqlite3
        db = str(tmp_path / "events.db")
        store = EventStore(db)
        e = order_proposed({"client_order_id": "co-1", "symbol": "X", "side": "BUY", "qty": 75})
        store.append(e)
        with pytest.raises(sqlite3.IntegrityError):
            store.append(e)
        store.close()


class TestPreFlightRejectsLimitAtBadPrice:
    """The 15:15 IST close_None chaos happened because LLM proposed limit=113
    when bid=12. This test guards against that."""

    def test_sell_limit_too_far_above_bid_is_rejected(self):
        """SELL LIMIT 113 when bid=12 must be rejected pre-flight."""
        proj = StateProjection()
        # Inject a tick with bid=12
        proj.apply(market_tick("NIFTY01OCT2622750CE", ltp=12.0, bid=12.0, ask=12.5))
        proj.account.cash = 100000.0

        gate = PreFlight()
        order = {
            "client_order_id": "co-test-1",
            "symbol": "NIFTY01OCT2622750CE",
            "underlying": "NIFTY",
            "side": "SELL",
            "qty": 75,
            "order_type": "LIMIT",
            "price": 113.0,  # 9x bid — the broken-condor bug pattern
            "strike": 22750,
            "option_type": "CE",
            "expiry": "2026-10-01",
        }
        result = gate.check_order(order, proj)
        assert not result.ok, f"SELL LIMIT 113 (bid=12) must be rejected, got: {result.to_dict()}"
        assert result.gate == "limit_reasonable"
        assert "limit 113" in result.reason.lower() or "113" in result.reason

    def test_sell_limit_at_bid_is_accepted(self):
        """SELL LIMIT at bid (within tolerance) must pass."""
        proj = StateProjection()
        proj.apply(market_tick("NIFTY01OCT2622750CE", ltp=12.0, bid=12.0, ask=12.5))
        proj.account.cash = 100000.0

        gate = PreFlight()
        order = {
            "client_order_id": "co-test-2",
            "symbol": "NIFTY01OCT2622750CE",
            "underlying": "NIFTY",
            "side": "SELL",
            "qty": 75,
            "order_type": "LIMIT",
            "price": 12.5,  # 4% above bid — within 20% tolerance
            "strike": 22750,
            "option_type": "CE",
            "expiry": "2026-10-01",
        }
        result = gate.check_order(order, proj)
        assert result.ok, f"SELL LIMIT 12.5 (bid=12) should pass: {result.to_dict()}"

    def test_sell_limit_no_tick_data_is_rejected(self):
        """FIX: no tick data → fail CLOSED, not OPEN. This prevents 60s timeouts."""
        proj = StateProjection()
        proj.account.cash = 100000.0
        # No tick injected

        gate = PreFlight()
        order = {
            "client_order_id": "co-test-3",
            "symbol": "NIFTY01OCT2622750CE",
            "underlying": "NIFTY",
            "side": "SELL",
            "qty": 75,
            "order_type": "LIMIT",
            "price": 12.0,
            "strike": 22750,
            "option_type": "CE",
            "expiry": "2026-10-01",
        }
        result = gate.check_order(order, proj)
        assert not result.ok, "Without tick data, SELL LIMIT must be rejected"
        assert result.gate == "pricing"


class TestPreFlightAtomicPlan:
    """Multi-leg plans must be atomic. If ANY leg fails pre-flight, all fail."""

    def test_iron_condor_with_one_bad_leg_is_fully_rejected(self):
        """If 3 legs are OK but 1 has limit=113, the whole plan is rejected.
        This prevents the broken-condor state where BUYs fill but SELLs don't.
        """
        proj = StateProjection()
        # Inject ticks for ALL strikes involved
        for sym, ltp, bid, ask in [
            ("NIFTY01OCT2622950CE", 12.0, 12.0, 12.5),
            ("NIFTY01OCT2623050CE", 8.0, 8.0, 8.5),
            ("NIFTY01OCT2622550PE", 15.0, 15.0, 15.5),
            ("NIFTY01OCT2622450PE", 10.0, 10.0, 10.5),  # bid=10, but plan has limit=113
        ]:
            proj.apply(market_tick(sym, ltp, bid, ask))
        proj.account.cash = 100000.0

        gate = PreFlight()
        plan = {
            "strategy": "iron_condor_nifty",
            "underlying": "NIFTY",
            "legs": [
                {  # SELL body CE — OK
                    "client_order_id": "co-sell-ce",
                    "symbol": "NIFTY01OCT2622950CE",
                    "underlying": "NIFTY",
                    "side": "SELL", "qty": 75, "order_type": "MARKET",
                    "strike": 22950, "option_type": "CE", "expiry": "2026-10-01",
                },
                {  # BUY wing CE — OK
                    "client_order_id": "co-buy-ce",
                    "symbol": "NIFTY01OCT2623050CE",
                    "underlying": "NIFTY",
                    "side": "BUY", "qty": 75, "order_type": "MARKET",
                    "strike": 23050, "option_type": "CE", "expiry": "2026-10-01",
                },
                {  # SELL body PE — OK
                    "client_order_id": "co-sell-pe",
                    "symbol": "NIFTY01OCT2622550PE",
                    "underlying": "NIFTY",
                    "side": "SELL", "qty": 75, "order_type": "MARKET",
                    "strike": 22550, "option_type": "PE", "expiry": "2026-10-01",
                },
                {  # BUY wing PE — has limit=113 way above bid (the broken-condor bug)
                    "client_order_id": "co-buy-pe-bad",
                    "symbol": "NIFTY01OCT2622450PE",
                    "underlying": "NIFTY",
                    "side": "BUY", "qty": 75, "order_type": "LIMIT",
                    "price": 113.0,  # 10x above the 12-ish bid for this strike
                    "strike": 22450, "option_type": "PE", "expiry": "2026-10-01",
                },
            ],
            "target": 0.0, "stop": 0.0, "confidence": 0.0, "reason": "iron condor",
        }
        result = gate.check_plan(plan, proj)
        # The plan has a bad leg, so the whole plan must fail
        assert not result.ok, f"BAD-LEG plan must fail atomically, got: {result.to_dict()}"
        assert result.gate in ("limit_reasonable", "per_trade_cap", "structure"), (
            f"Expected a risk gate failure, got: {result.gate}"
        )

    def test_atomic_full_iron_condor_passes(self):
        """A well-formed iron condor with all market orders passes."""
        proj = StateProjection()
        # Inject ticks for ALL strikes involved
        for sym, ltp, bid, ask in [
            ("NIFTY01OCT2622950CE", 12.0, 12.0, 12.5),
            ("NIFTY01OCT2623050CE", 8.0, 8.0, 8.5),
            ("NIFTY01OCT2622550PE", 15.0, 15.0, 15.5),
            ("NIFTY01OCT2622450PE", 10.0, 10.0, 10.5),
        ]:
            proj.apply(market_tick(sym, ltp, bid, ask))
        proj.account.cash = 100000.0

        gate = PreFlight()
        plan = {
            "strategy": "iron_condor_nifty",
            "underlying": "NIFTY",
            "legs": [
                {"client_order_id": f"co-{i}", "symbol": s, "underlying": "NIFTY",
                 "side": side, "qty": 75, "order_type": "MARKET",
                 "strike": strike, "option_type": ot, "expiry": "2026-10-01"}
                for i, (s, side, strike, ot) in enumerate([
                    ("NIFTY01OCT2622950CE", "SELL", 22950, "CE"),
                    ("NIFTY01OCT2623050CE", "BUY", 23050, "CE"),
                    ("NIFTY01OCT2622550PE", "SELL", 22550, "PE"),
                    ("NIFTY01OCT2622450PE", "BUY", 22450, "PE"),
                ])
            ],
            "target": 0.0, "stop": 0.0, "confidence": 0.0, "reason": "iron condor",
        }
        result = gate.check_plan(plan, proj)
        assert result.ok, f"Well-formed iron condor should pass: {result.to_dict()}"


class TestPreFlightPerTradeCap:
    """Per-trade cap should reject orders that exceed it."""

    def test_per_trade_cap_rejects_oversized_buy(self):
        """BUY 100 lots exceeds 5% per-trade cap on 100k cash."""
        proj = StateProjection()
        proj.apply(market_tick("NIFTY01OCT2622950CE", ltp=100.0, bid=99.0, ask=100.0))
        proj.account.cash = 100000.0

        gate = PreFlight()
        order = {
            "client_order_id": "co-big",
            "symbol": "NIFTY01OCT2622950CE",
            "underlying": "NIFTY",
            "side": "BUY", "qty": 75 * 50,  # 50 lots
            "order_type": "MARKET",
            "strike": 22950, "option_type": "CE", "expiry": "2026-10-01",
        }
        result = gate.check_order(order, proj)
        assert not result.ok
        assert result.gate == "per_trade_cap"


class TestEventStoreRejectionRecording:
    """Rejections must be recorded so the LLM gets feedback."""

    def test_rejection_event_has_reason_and_gate(self, tmp_path):
        db = str(tmp_path / "events.db")
        store = EventStore(db)
        proj = StateProjection()

        # Reject an order
        order = {"symbol": "X", "side": "BUY", "qty": 75, "order_type": "MARKET"}
        evt = order_rejected(order, "limit 113 too far above bid", "limit_reasonable")
        store.append(evt)
        proj.apply(evt)
        assert len(proj.rejected_orders) == 1
        rec = proj.rejected_orders[0]
        assert rec["reason"] == "limit 113 too far above bid"
        assert rec["gate"] == "limit_reasonable"
        store.close()


class TestWebSocketBroadcast:
    """WebSocket clients must receive event broadcasts."""

    def test_websocket_connects_and_sends_initial_snapshot(self):
        """A connected client receives an initial state snapshot."""
        from fastapi.testclient import TestClient
        from system.core.api.server import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "state.db")
            app = create_app(db_path)
            try:
                with TestClient(app) as client:
                    with client.websocket_connect("/ws") as ws:
                        # First message is the snapshot
                        msg = ws.receive_json()
                        assert msg["type"] == "snapshot"
                        assert "data" in msg
                        assert "account" in msg["data"]
                        # Ping/pong
                        ws.send_text("ping")
                        assert ws.receive_text() == "pong"
            finally:
                app.state.store.close()

    def test_websocket_receives_event_broadcast(self):
        """When a tick event is appended, all connected clients get it."""
        from fastapi.testclient import TestClient
        from system.core.api.server import create_app

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "state.db")
            app = create_app(db_path)
            try:
                with TestClient(app) as client:
                    with client.websocket_connect("/ws") as ws:
                        # Drain initial snapshot
                        ws.receive_json()

                        # Post a tick via the API
                        r = client.post(
                            "/api/market_tick",
                            params={"symbol": "NIFTY", "ltp": 22750.0, "bid": 22749.0, "ask": 22751.0},
                        )
                        assert r.status_code == 200

                        # Client should receive the event
                        msg = ws.receive_json()
                        assert msg["type"] == "events"
                        assert len(msg["data"]) >= 1
                        ev = msg["data"][0]
                        assert ev["type"] == "market.tick"
                        assert ev["payload"]["symbol"] == "NIFTY"
            finally:
                app.state.store.close()