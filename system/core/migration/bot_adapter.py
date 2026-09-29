"""Bot → Core adapter (Phase 2 migration bridge).

The legacy bot writes JSON files via PaperClient._save_state(). This
adapter intercepts those writes and emits equivalent events to the new
core's SQLite event store. The bot stays unchanged; this is a
side-channel.

Behavior:
- For each _save_state() call, diff against previous state
- Emit events for: orders placed/filled/c, positions opened/changed/closed,
  cash changes, realized P&L changes
- Falls back silently if core is unavailable (bot continues to work)
- Writes to core on EVERY save (every 2-5s), so core is always fresh

This is the Phase 2 bridge. Once verified, Phase 3 swaps the bot's
JSON writes for direct core API calls.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..store.event_store import EventStore
from ..domain.events import (
    Event, EventType,
    order_proposed, order_placed, order_filled, order_cancelled,
    plan_completed,
    market_tick,
)


logger = logging.getLogger(__name__)


class BotAdapter:
    """Reads the bot's JSON state and mirrors it to core events."""

    def __init__(self, json_path: str, store: EventStore, projection=None):
        self.json_path = Path(json_path)
        self.store = store
        # FIX 2026-09-29 21:35: also apply to the in-memory projection so the
        # running core's state is fresh without restart.
        self.projection = projection
        self.last_orders: dict[str, dict] = {}
        self.last_positions: dict[str, dict] = {}
        self.last_cash: float = 0.0
        self.last_realized: float = 0.0
        self._mtime = 0.0
        # Counter to skip no-change syncs (cheap)
        self._last_sync_count = 0

    def _read_state(self) -> Optional[dict]:
        """Read the JSON state. Returns None if unavailable."""
        try:
            with open(self.json_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return None
        except Exception as e:
            logger.warning(f"BotAdapter: failed to read {self.json_path}: {e}")
            return None

    def sync_once(self) -> int:
        """Read JSON once, emit events for diffs. Returns event count."""
        try:
            mtime = self.json_path.stat().st_mtime
        except (FileNotFoundError, OSError):
            return 0
        if abs(mtime - self._mtime) < 0.01:
            return 0

        state = self._read_state()
        if state is None:
            return 0

        events: list[Event] = []
        now_iso = datetime.utcnow().isoformat()

        new_orders = state.get("orders", {})
        new_positions = state.get("positions", {})
        new_cash = float(state.get("cash", 0))
        new_realized = float(state.get("realized_pnl", 0))

        # ---- ORDERS ----
        for oid, o in new_orders.items():
            old = self.last_orders.get(oid, {})
            status = o.get("status", "")
            old_status = old.get("status", "")
            # New order
            if not old:
                events.append(order_proposed({
                    "client_order_id": o.get("client_order_id") or oid,
                    "broker_order_id": oid,
                    "symbol": o.get("symbol", ""),
                    "underlying": o.get("underlying", ""),
                    "side": o.get("side", ""),
                    "qty": int(o.get("qty", 0) or 0),
                    "order_type": o.get("order_type", "MARKET"),
                    "product": o.get("product", "MIS"),
                    "price": float(o.get("price", 0) or 0),
                    "tag": o.get("tag", ""),
                    "strike": float(o.get("strike", 0) or 0),
                    "option_type": o.get("option_type", ""),
                    "expiry": o.get("expiry", ""),
                    "exchange": o.get("exchange", "NFO"),
                }))
            # Status changed
            if status != old_status:
                if status == "PLACED" and old_status != "PLACED":
                    events.append(order_placed(
                        {"client_order_id": oid},
                        broker_order_id=oid,
                    ))
                elif status == "COMPLETE" or status == "FILLED":
                    events.append(order_filled(
                        order_id=oid,
                        fill_price=float(o.get("avg_fill_price", 0) or 0),
                        filled_qty=int(o.get("filled_qty", 0) or 0),
                    ))
                elif status in ("CANCELLED", "REJECTED"):
                    events.append(order_cancelled(oid))

        # ---- POSITIONS ----
        for sym, p in new_positions.items():
            old = self.last_positions.get(sym, {})
            qty = int(p.get("qty", 0) or 0)
            old_qty = int(old.get("qty", 0) or 0)
            ltp = float(p.get("ltp", 0) or 0)
            # New position
            if not old and qty != 0:
                events.append(order_filled(
                    order_id=f"legacy-{sym}",
                    fill_price=float(p.get("avg_price", 0) or 0),
                    filled_qty=qty,
                    symbol=sym,
                    side="BUY" if qty > 0 else "SELL",
                ))
            # Quantity change
            elif qty != old_qty and qty != 0:
                events.append(order_filled(
                    order_id=f"legacy-{sym}",
                    fill_price=float(p.get("avg_price", 0) or 0),
                    filled_qty=qty - old_qty,
                    symbol=sym,
                    side="BUY" if (qty - old_qty) > 0 else "SELL",
                ))
            # Position closed
            elif sym in self.last_positions and qty == 0:
                events.append(order_cancelled(f"legacy-{sym}"))
            # Tick
            if ltp > 0:
                events.append(market_tick(
                    symbol=sym,
                    ltp=ltp,
                    bid=ltp,
                    ask=ltp,
                ))

        # Closed positions in the new state
        for sym in self.last_positions:
            if sym not in new_positions:
                events.append(order_cancelled(f"legacy-{sym}"))

        # ---- ACCOUNT ----
        if abs(new_cash - self.last_cash) > 0.01 or abs(new_realized - self.last_realized) > 0.01:
            events.append(Event(
                type=EventType.ORDER_FILLED,
                actor="bot_bridge",
                payload={
                    "delta_cash": new_cash - self.last_cash,
                    "delta_realized": new_realized - self.last_realized,
                    "source": "bot_bridge",
                },
            ))

        # Append to store (best-effort, don't break bot if core is down)
        try:
            self.store.append_batch(events)
            # FIX 2026-09-29 21:35: also apply to in-memory projection
            if self.projection is not None:
                for e in events:
                    self.projection.apply(e)
        except Exception as e:
            logger.warning(f"BotAdapter: core append failed (continuing): {e}")

        # Update state cache
        self.last_orders = new_orders
        self.last_positions = new_positions
        self.last_cash = new_cash
        self.last_realized = new_realized
        self._mtime = mtime
        self._last_sync_count += len(events)
        return len(events)

    def run_forever(self, poll_interval: float = 1.0):
        """Poll the JSON file forever, syncing to events."""
        logger.info(f"BotAdapter watching {self.json_path}")
        import time as _t
        while True:
            try:
                n = self.sync_once()
                if n > 0:
                    logger.debug(f"bot bridge: emitted {n} events (total: {self._last_sync_count})")
            except Exception as e:
                logger.error(f"BotAdapter sync error: {e}")
            _t.sleep(poll_interval)


# ----- Runner -----

if __name__ == "__main__":
    import argparse
    import sys as _sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", default="data_cache/paper_state.json")
    parser.add_argument("--db", default="data_cache/state.db")
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args()
    store = EventStore(args.db)
    adapter = BotAdapter(args.json, store)
    try:
        adapter.run_forever(args.interval)
    except KeyboardInterrupt:
        store.close()
        _sys.exit(0)