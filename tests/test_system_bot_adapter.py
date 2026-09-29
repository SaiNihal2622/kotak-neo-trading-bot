"""Tests for the bot adapter (legacy bot JSON → core events bridge)."""
import json
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "system"))


class TestBotAdapterEmitsEventsForJSONChanges:
    """BotAdapter watches the legacy bot's paper_state.json and emits core events."""

    def test_new_position_emits_fill_event(self, tmp_path):
        from system.core.store.event_store import EventStore
        from system.core.migration.bot_adapter import BotAdapter

        db_path = str(tmp_path / "state.db")
        json_path = str(tmp_path / "paper_state.json")
        Path(json_path).write_text(json.dumps({
            "cash": 100000.0, "realized_pnl": 0.0, "orders": {},
            "positions": {},
        }))

        store = EventStore(db_path)
        adapter = BotAdapter(json_path, store)
        adapter.sync_once()  # initial sync (no diff)

        # Add a new position
        Path(json_path).write_text(json.dumps({
            "cash": 99000.0, "realized_pnl": 0.0,
            "orders": {"PAPER-1": {"status": "COMPLETE", "symbol": "NIFTY",
                                  "side": "BUY", "qty": 75, "avg_fill_price": 100.0,
                                  "order_type": "MARKET", "product": "MIS",
                                  "strike": 0, "option_type": "", "expiry": "",
                                  "exchange": "NFO"}},
            "positions": {"NIFTY": {"qty": 75, "avg_price": 100.0, "ltp": 100.0,
                                    "strike": 0, "option_type": "", "expiry": "",
                                    "underlying": "NIFTY", "exchange": "NFO"}},
        }))
        n = adapter.sync_once()
        assert n > 0, "Adding a position + order should emit events"
        store.close()

    def test_cash_change_emits_event(self, tmp_path):
        from system.core.store.event_store import EventStore
        from system.core.migration.bot_adapter import BotAdapter

        db_path = str(tmp_path / "state.db")
        json_path = str(tmp_path / "paper_state.json")
        Path(json_path).write_text(json.dumps({
            "cash": 100000.0, "realized_pnl": 0.0, "orders": {}, "positions": {},
        }))

        store = EventStore(db_path)
        adapter = BotAdapter(json_path, store)
        adapter.sync_once()

        # Cash changes
        Path(json_path).write_text(json.dumps({
            "cash": 95000.0, "realized_pnl": -5000.0,
            "orders": {}, "positions": {},
        }))
        n = adapter.sync_once()
        assert n > 0, "Cash change should emit event"
        store.close()

    def test_no_diff_no_events(self, tmp_path):
        """Same JSON content → no events emitted."""
        from system.core.store.event_store import EventStore
        from system.core.migration.bot_adapter import BotAdapter

        db_path = str(tmp_path / "state.db")
        json_path = str(tmp_path / "paper_state.json")
        Path(json_path).write_text(json.dumps({
            "cash": 100000.0, "realized_pnl": 0.0, "orders": {}, "positions": {},
        }))

        store = EventStore(db_path)
        adapter = BotAdapter(json_path, store)
        adapter.sync_once()  # initial

        # Same content
        n = adapter.sync_once()
        assert n == 0, "No change → no events"
        store.close()

    def test_missing_json_file_returns_zero(self, tmp_path):
        """Adapter must not crash if the JSON file doesn't exist."""
        from system.core.store.event_store import EventStore
        from system.core.migration.bot_adapter import BotAdapter

        db_path = str(tmp_path / "state.db")
        json_path = str(tmp_path / "paper_state.json")  # doesn't exist
        store = EventStore(db_path)
        adapter = BotAdapter(json_path, store)
        n = adapter.sync_once()
        assert n == 0
        store.close()

    def test_bot_adapter_state_visible_via_core_api(self, tmp_path):
        """End-to-end: bot JSON → adapter → core API returns the state."""
        from fastapi.testclient import TestClient
        from system.core.api.server import create_app
        from system.core.store.event_store import EventStore
        from system.core.migration.bot_adapter import BotAdapter

        db_path = str(tmp_path / "state.db")
        json_path = str(tmp_path / "paper_state.json")
        Path(json_path).write_text(json.dumps({
            "cash": 89000.0, "realized_pnl": -10000.0,
            "orders": {}, "positions": {},
        }))

        app = create_app(db_path)
        try:
            store = app.state.store
            # FIX 2026-09-29 21:35: pass projection so adapter updates in-memory state
            adapter = BotAdapter(json_path, store, projection=app.state.projection)
            adapter.sync_once()

            with TestClient(app) as client:
                # Add a position
                Path(json_path).write_text(json.dumps({
                    "cash": 88000.0, "realized_pnl": -10000.0,
                    "orders": {},
                    "positions": {"NIFTY": {"qty": 75, "avg_price": 100.0, "ltp": 105.0,
                                            "underlying": "NIFTY", "exchange": "NFO"}},
                }))
                adapter.sync_once()

                r = client.get("/api/state")
                assert r.status_code == 200
                snapshot = r.json()
                assert "NIFTY" in snapshot["positions"]
                assert snapshot["positions"]["NIFTY"]["qty"] == 75
        finally:
            app.state.store.close()