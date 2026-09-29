"""Exec gateway — Phase 5: closes the loop.

Reads ORDER_PROPOSED events from the core, places orders via the broker,
and emits ORDER_FILLED events back to the core. This is the final piece
that allows the legacy bot to be decommissioned.

Flow:
1. Brain proposes plan via /api/plan → core emits ORDER_PROPOSED events
2. Exec gateway subscribes to /ws (or polls /api/events)
3. For each ORDER_PROPOSED without a corresponding fill:
   - Build a paper Order from the event payload
   - Call broker.place_order()
   - Emit ORDER_FILLED event with the result

The exec gateway is the only piece that calls broker.place_order() in
the new architecture. The brain and the UI don't touch the broker.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
import websockets


logger = logging.getLogger(__name__)


CORE_URL = "http://127.0.0.1:8510"
CORE_WS = "ws://127.0.0.1:8510/ws"


class ExecGateway:
    """Listens for ORDER_PROPOSED events, places orders, emits fills."""

    def __init__(
        self,
        core_url: str = CORE_URL,
        broker_module: str = "kotak_bot.broker.paper_client",
        dry_run: bool = True,
        http_session: Optional["requests.Session"] = None,
    ):
        self.core_url = core_url.rstrip("/")
        self.broker_module = broker_module
        self.dry_run = dry_run
        self.broker = None
        self.processed_orders: set[str] = set()
        self.last_event_ts: str = ""
        # PHASE 5 FIX 2026-09-29: allow tests to inject a session (or mock) so
        # the gateway doesn't need real network for fill emission. Default to
        # a fresh requests.Session.
        self._http = http_session or requests.Session()

    def _load_broker(self):
        """Lazy-load the broker to avoid hard dependency at module import."""
        if self.broker is not None:
            return self.broker
        try:
            import importlib
            mod = importlib.import_module(self.broker_module)
            self.broker = mod.PaperClient()
            self.broker.connect()
            logger.info(f"loaded broker: {self.broker_module}")
        except Exception as e:
            logger.warning(f"failed to load broker ({self.broker_module}): {e}")
            self.broker = None
        return self.broker

    async def _post_fill(self, order_id: str, fill_price: float, filled_qty: int, status: str = "FILLED"):
        """Emit an ORDER_FILLED event back to the core.

        The order_id must be the client_order_id (or broker_order_id) that
        the core's StateProjection can resolve via _find_order(). Pass
        client_order_id by default — that's what OrderProposal sets in the
        ORDER_PROPOSED event.
        """
        try:
            payload = {
                "order_id": order_id,
                "fill_price": float(fill_price),
                "filled_qty": int(filled_qty),
            }
            r = self._http.post(
                f"{self.core_url}/api/order_fill",
                json=payload,
                timeout=5,
            )
            if r.status_code == 200:
                logger.info(f"fill emitted for {order_id}: {fill_price}×{filled_qty}")
            else:
                logger.warning(
                    f"fill emission failed for {order_id}: {r.status_code} {r.text[:200]}"
                )
        except Exception as e:
            logger.error(f"fill emission failed for {order_id}: {e}")

    async def _handle_order_event(self, event: dict):
        """Process an ORDER_PROPOSED event by placing the order."""
        if event.get("type") != "order.proposed":
            return
        eid = event.get("id", "")
        # PHASE 5 FIX 2026-09-29: dedup by client_order_id, not event ID.
        # If the WS reconnects and replays events, the event ID changes but
        # the client_order_id stays the same — deduping by event ID would
        # cause us to re-place the same order. Deduping by client_order_id
        # is correct because that's the ID we POST to /api/order_fill.
        client_order_id = event.get("payload", {}).get("client_order_id", "")
        dedup_key = client_order_id or eid
        if dedup_key in self.processed_orders:
            return
        self.processed_orders.add(dedup_key)

        payload = event.get("payload", {})
        symbol = payload.get("symbol")
        if not symbol:
            return

        logger.info(f"processing order.proposed: {symbol} {payload.get('side')} {payload.get('qty')} (client_order_id={client_order_id})")

        broker = self._load_broker()
        if broker is None:
            logger.warning("broker unavailable, skipping")
            return

        # Build a paper Order
        try:
            from kotak_bot.broker.base import Order, OrderSide, OrderType, ProductType
            order = Order(
                symbol=payload.get("symbol"),
                side=OrderSide(payload.get("side", "BUY")),
                qty=int(payload.get("qty", 0)),
                order_type=OrderType(payload.get("order_type", "MARKET")),
                product=ProductType.MIS,
                price=float(payload.get("price", 0) or 0),
                tag=payload.get("tag", "EXEC-GATEWAY"),
                exchange=payload.get("exchange", "NFO"),
                strike=float(payload.get("strike", 0) or 0),
                option_type=payload.get("option_type", ""),
                expiry=payload.get("expiry", ""),
                underlying=payload.get("underlying", ""),
            )
            if self.dry_run:
                logger.info(f"[DRY-RUN] would place: {order.symbol} {order.side.value} {order.qty}")
                # PHASE 5 FIX 2026-09-29: dry-run now emits fills even without
                # a tick price (uses the order's price, or 0 as last resort).
                # The whole point of dry-run is to validate the integration
                # end-to-end without market exposure — skipping fills defeats it.
                # Try to fetch a tick price for more realistic fills.
                fill_price = float(order.price) if order.price > 0 else 0.0
                if fill_price <= 0:
                    try:
                        r = self._http.get(f"{self.core_url}/api/state", timeout=3)
                        state = r.json()
                        # Look up the tick for this symbol
                        ticks = state.get("ticks", {})
                        tick = ticks.get(order.symbol, {})
                        if tick:
                            # Use bid for SELL (we sell at bid), ask for BUY
                            if order.side.value == "BUY":
                                fill_price = float(tick.get("ask", 0) or tick.get("ltp", 0) or 0)
                            else:
                                fill_price = float(tick.get("bid", 0) or tick.get("ltp", 0) or 0)
                    except Exception:
                        pass
                if fill_price <= 0:
                    logger.debug(
                        f"DRY-RUN: no tick price for {order.symbol}, emitting fill @ 0.0"
                    )
                # Always emit fill so the state projection updates. Use
                # client_order_id (the projection's _find_order() resolves by it).
                await self._post_fill(client_order_id or eid, fill_price, order.qty)
                return

            filled = broker.place_order(order)
            if filled.status.value in ("complete", "filled", "open"):
                # Use client_order_id so the projection can resolve the order
                await self._post_fill(
                    client_order_id or eid,
                    float(filled.avg_fill_price or order.price),
                    int(filled.qty),
                )
                logger.info(f"placed {symbol}: status={filled.status.value} fill={filled.avg_fill_price}")
            else:
                logger.warning(f"order rejected: {filled.rejection_reason}")
                # Emit a rejection event so the core records it
                try:
                    self._http.post(
                        f"{self.core_url}/api/order_reject",
                        json={"order_id": client_order_id or eid, "reason": filled.rejection_reason},
                        timeout=5,
                    )
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"order placement failed for {client_order_id or eid}: {e}\n{traceback.format_exc()}")

    async def run_forever(self):
        """Subscribe to /ws, process order events forever."""
        ws_uri = self.core_url.replace("http://", "ws://") + "/ws"
        backoff = 1.0
        while True:
            try:
                logger.info(f"connecting to {ws_uri}...")
                async with websockets.connect(ws_uri) as ws:
                    logger.info(f"connected: {ws_uri}")
                    backoff = 1.0
                    # First message is snapshot; drain it
                    await ws.recv()
                    # Then process events
                    while True:
                        try:
                            msg = await ws.recv()
                            data = json.loads(msg)
                            if data.get("type") == "events":
                                for event in data.get("data", []):
                                    if event.get("type") == "order.proposed":
                                        await self._handle_order_event(event)
                        except Exception as inner:
                            logger.warning(f"inner error: {inner}")
                            break
            except Exception as e:
                logger.error(f"WS connection failed: {e}, retrying in {backoff}s")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)


def main():
    import argparse
    import os
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [EXEC-GW] %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--core", default=os.environ.get("KOTAK_CORE_URL", CORE_URL))
    parser.add_argument("--broker", default="kotak_bot.broker.paper_client")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--live", action="store_true", help="actually place orders")
    args = parser.parse_args()
    gateway = ExecGateway(
        core_url=args.core,
        broker_module=args.broker,
        dry_run=not args.live,
    )
    asyncio.run(gateway.run_forever())


if __name__ == "__main__":
    main()