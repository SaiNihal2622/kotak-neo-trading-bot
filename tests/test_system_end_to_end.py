"""End-to-end test of the full system: bot JSON → adapter → core → API → UI."""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "system"))


class TestEndToEndFlow:
    """Simulates the full production flow without a real broker."""

    def test_bot_json_to_ui_via_core(self, tmp_path):
        """Full chain: bot writes JSON → adapter bridges → core API serves → UI reads."""
        from fastapi.testclient import TestClient
        from system.core.api.server import create_app
        from system.core.store.event_store import EventStore
        from system.core.migration.bot_adapter import BotAdapter

        # 1. Simulate the legacy bot writing paper_state.json
        db_path = str(tmp_path / "state.db")
        json_path = str(tmp_path / "paper_state.json")
        Path(json_path).write_text(json.dumps({
            "cash": 95000.0, "realized_pnl": -5000.0,
            "orders": {
                "PAPER-1": {
                    "status": "COMPLETE",
                    "symbol": "NIFTY01OCT2622950CE", "underlying": "NIFTY",
                    "side": "BUY", "qty": 75, "avg_fill_price": 4.50,
                    "order_type": "MARKET", "product": "MIS",
                    "strike": 22950, "option_type": "CE", "expiry": "2026-10-01",
                    "exchange": "NFO", "tag": "QUANT-iron_condor",
                }
            },
            "positions": {
                "NIFTY01OCT2622950CE": {
                    "qty": 75, "avg_price": 4.50, "ltp": 5.20,
                    "underlying": "NIFTY", "exchange": "NFO",
                    "strike": 22950, "option_type": "CE", "expiry": "2026-10-01",
                    "product": "MIS",
                }
            }
        }))

        # 2. Start the core
        app = create_app(db_path)
        try:
            # 3. Start the bot adapter (bridges JSON → events)
            adapter = BotAdapter(json_path, app.state.store, projection=app.state.projection)
            adapter.sync_once()

            with TestClient(app) as client:
                # 4. Core API reflects the bot's state
                state = client.get("/api/state").json()
                assert "NIFTY01OCT2622950CE" in state["positions"], (
                    "Position from bot JSON must appear in core state"
                )
                pos = state["positions"]["NIFTY01OCT2622950CE"]
                assert pos["qty"] == 75
                assert pos["avg_price"] == 4.50
                assert abs(pos["pnl"] - (5.20 - 4.50) * 75) < 0.01

                # 5. Health check works
                health = client.get("/healthz").json()
                assert health["ok"] is True
                assert health["events_in_log"] > 0

                # 6. Metrics expose key signals
                metrics = client.get("/api/metrics").text
                assert "kotak_positions_count" in metrics
                assert "kotak_cash" in metrics

                # 7. The position is queryable
                positions = client.get("/api/positions").json()
                assert "NIFTY01OCT2622950CE" in positions["positions"]
        finally:
            app.state.store.close()

    def test_pre_flight_blocks_bad_plan_e2e(self, tmp_path):
        """Submit a plan with limit=113 via /api/plan → pre-flight rejects."""
        from fastapi.testclient import TestClient
        from system.core.api.server import create_app

        db_path = str(tmp_path / "state.db")
        app = create_app(db_path)
        try:
            with TestClient(app) as client:
                # Inject a tick (low bid)
                client.post(
                    "/api/market_tick",
                    params={"symbol": "NIFTY01OCT2622950CE", "ltp": 12.0, "bid": 12.0, "ask": 12.5},
                )
                # Submit the broken-condor pattern
                bad_plan = {
                    "strategy": "iron_condor_nifty",
                    "underlying": "NIFTY",
                    "legs": [
                        {"symbol": "NIFTY01OCT2622950CE", "underlying": "NIFTY",
                         "side": "SELL", "qty": 75, "order_type": "LIMIT",
                         "price": 113.0,  # 9x bid — broken-condor pattern
                         "strike": 22950, "option_type": "CE", "expiry": "2026-10-01"}
                    ],
                }
                r = client.post("/api/plan", json=bad_plan)
                # Plan rejected by pre-flight (single leg = atomic, but limit too high)
                assert r.status_code == 400, "Plan with bad limit must be rejected"
                error = r.json().get("error", {})
                assert error.get("gate") == "limit_reasonable"
                # The rejection event is in the events log
                events = client.get("/api/events?types=order.rejected").json()
                assert any(
                    e.get("payload", {}).get("gate") == "limit_reasonable"
                    for e in events["events"]
                ), f"Expected limit_reasonable rejection, got: {events}"
        finally:
            app.state.store.close()

    def test_healthz_reports_real_event_count(self, tmp_path):
        """After multiple events, healthz returns the count."""
        from fastapi.testclient import TestClient
        from system.core.api.server import create_app

        db_path = str(tmp_path / "state.db")
        app = create_app(db_path)
        try:
            with TestClient(app) as client:
                initial = client.get("/healthz").json()
                initial_count = initial["events_in_log"]
                # Add 3 events
                for i in range(3):
                    client.post(
                        "/api/market_tick",
                        params={"symbol": f"N{i}", "ltp": 100.0, "bid": 99.0, "ask": 101.0},
                    )
                after = client.get("/healthz").json()
                assert after["events_in_log"] >= initial_count + 3
        finally:
            app.state.store.close()