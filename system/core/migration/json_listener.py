"""JSON → SQLite listener (Phase 0 migration).

The legacy bot writes to JSON files (paper_state.json, etc.). This
script watches those files and writes equivalent events to the new core's
SQLite event store. Until the bot is migrated (Phase 2), this keeps the
two systems in sync.

Strategy:
- Tail paper_state.json's mtime
- When it changes, diff against previous state
- Emit events for diffs (positions added/removed, cash changed, etc.)
- Single writer: this script owns the SQLite DB during migration

This is a TEMPORARY bridge. Phase 2 migrates the bot to write directly.
"""
from __future__ import annotations

import json
import time
import logging
from pathlib import Path

from ..store.event_store import EventStore
from ..domain.events import (
    order_placed, order_filled, order_cancelled,
    plan_completed, plan_failed,
    market_tick,
)
from ..domain.state import StateProjection, AccountState, Position


logger = logging.getLogger(__name__)


class JsonListener:
    """Watches legacy JSON state and emits events to SQLite."""

    def __init__(self, json_path: str, store: EventStore):
        self.json_path = Path(json_path)
        self.store = store
        self.last_mtime = 0.0
        self.last_state: dict = {}
        self.projection = StateProjection()

    def _load_state(self) -> dict:
        try:
            with open(self.json_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"load failed: {e}")
            return {}

    def _diff_positions(self, new_positions: dict) -> list:
        """Return list of position changes since last sync."""
        events = []
        old_positions = self.last_state.get("positions", {})
        # New positions
        for sym, pos in new_positions.items():
            old = old_positions.get(sym, {})
            if not old:
                # New position opened
                events.append(order_filled(
                    order_id=f"legacy-{sym}",
                    fill_price=pos.get("avg_price", 0),
                    filled_qty=pos.get("qty", 0),
                ))
            elif abs(pos.get("qty", 0) - old.get("qty", 0)) > 0:
                # Quantity changed
                events.append(order_filled(
                    order_id=f"legacy-{sym}",
                    fill_price=pos.get("avg_price", 0),
                    filled_qty=pos.get("qty", 0) - old.get("qty", 0),
                ))
        # Closed positions
        for sym in old_positions:
            if sym not in new_positions:
                events.append(order_cancelled(f"legacy-{sym}"))
        return events

    def _diff_cash(self, new_cash: float, new_realized: float) -> list:
        """Return cash/realized change events."""
        old_cash = self.last_state.get("cash", 0)
        old_realized = self.last_state.get("realized_pnl", 0)
        events = []
        if abs(new_cash - old_cash) > 0.01 or abs(new_realized - old_realized) > 0.01:
            # Emit a synthetic event
            from ..domain.events import Event, EventType
            events.append(Event(
                type=EventType.ORDER_FILLED,
                actor="legacy_bridge",
                payload={
                    "delta_cash": new_cash - old_cash,
                    "delta_realized": new_realized - old_realized,
                    "source": "json_bridge",
                },
            ))
        return events

    def sync_once(self) -> int:
        """Read JSON once, emit diff events. Returns number of events emitted."""
        try:
            mtime = self.json_path.stat().st_mtime
        except FileNotFoundError:
            return 0
        if abs(mtime - self.last_mtime) < 0.01 and self.last_state:
            return 0  # no change

        new_state = self._load_state()
        if not new_state:
            return 0

        events = []
        # Cash + realized
        events.extend(self._diff_cash(
            new_state.get("cash", 0),
            new_state.get("realized_pnl", 0),
        ))
        # Positions
        events.extend(self._diff_positions(new_state.get("positions", {})))
        # Tick (for the underlying)
        for sym, pos in new_state.get("positions", {}).items():
            if pos.get("ltp", 0) > 0:
                events.append(market_tick(
                    symbol=sym,
                    ltp=pos.get("ltp", 0),
                    bid=pos.get("ltp", 0),
                    ask=pos.get("ltp", 0),
                ))
                break  # one tick is enough for snapshot

        for e in events:
            self.store.append(e)
        self.last_state = new_state
        self.last_mtime = mtime
        return len(events)

    def run_forever(self, poll_interval: float = 2.0):
        """Poll the JSON file and emit events."""
        logger.info(f"JsonListener started: watching {self.json_path}")
        while True:
            try:
                n = self.sync_once()
                if n > 0:
                    logger.info(f"emitted {n} events from JSON state diff")
            except Exception as e:
                logger.error(f"sync error: {e}")
            time.sleep(poll_interval)


# ----- Runner -----

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", default="data_cache/paper_state.json")
    parser.add_argument("--db", default="data_cache/state.db")
    parser.add_argument("--interval", type=float, default=2.0)
    args = parser.parse_args()
    store = EventStore(args.db)
    listener = JsonListener(args.json, store)
    try:
        listener.run_forever(args.interval)
    except KeyboardInterrupt:
        store.close()