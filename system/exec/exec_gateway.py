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
import os
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




def _now_iso_ist() -> str:
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).isoformat()


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
        # FIX 2026-10-14: fills must reach paper_state.json (the store the
        # dashboard/journal/survival/bot read), not just the core's SQLite.
        self.paper_state_path = os.path.join("data_cache", "paper_state.json")
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

    async def _post_fill(self, order_id: str, fill_price: float, filled_qty: int, status: str = "FILLED") -> bool:
        """Emit an ORDER_FILLED event back to the core.

        The order_id must be the client_order_id (or broker_order_id) that
        the core's StateProjection can resolve via _find_order(). Pass
        client_order_id by default — that's what OrderProposal sets in the
        ORDER_PROPOSED event.

        Returns True if the fill was emitted successfully, False otherwise.
        Callers can use the return value to decide whether to fall back to
        the legacy broker path (PHASE 6 FIX 2026-09-30).
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
                return True
            logger.warning(
                f"fill emission failed for {order_id}: {r.status_code} {r.text[:200]}"
            )
        except Exception as e:
            logger.error(f"fill emission failed for {order_id}: {e}")
        return False

    def _sync_paper_state(self, order: dict, fill_price: float, filled_qty: int) -> None:
        """FIX 2026-10-14: the gateway fills into the core's SQLite event store,
        but the dashboard, journal, survival engine and bot read
        data_cache/paper_state.json. Without a write-back, every fill was
        stranded in an orphan store and the system LOOKED like it never traded
        (positions stayed 0, realized 0). Write the fill into paper_state.json.
        """
        try:
            import json as _j
            from pathlib import Path as _P
            _ps_path = _P(self.paper_state_path)
            _ps = {}
            if _ps_path.exists():
                try:
                    _ps = _j.loads(_ps_path.read_text(encoding="utf-8-sig"))
                except Exception:
                    _ps = {}
            _ps.setdefault("orders", {})
            _ps.setdefault("positions", {})
            sym = str(order.get("symbol", ""))
            side = str(order.get("side", "BUY"))
            _oid = str(order.get("client_order_id") or order.get("id") or sym)
            _ps["orders"][_oid] = {
                **_ps["orders"].get(_oid, {}),
                "filled_at": _now_iso_ist(),
                "symbol": sym, "side": side, "qty": filled_qty,
                "filled_qty": filled_qty, "avg_fill_price": float(fill_price),
                "status": "complete", "underlying": order.get("underlying", ""),
                "strike": order.get("strike", 0), "option_type": order.get("option_type", ""),
                "expiry": order.get("expiry", ""),
            }
            _pos = _ps["positions"].get(sym, {"qty": 0, "avg_price": 0.0, "symbol": sym})
            _cur = int(_pos.get("qty", 0) or 0)
            _delta = filled_qty if side == "BUY" else -filled_qty
            _new = _cur + _delta
            # FIX 2026-10-16: compute REALIZED P&L when a position closes.
            # A SELL that reduces a long (or BUY that reduces a short) realizes
            # (fill - avg) * closed_qty, signed by direction. This is what makes
            # the daily P&L / win-rate data actually materialize.
            _realized = 0.0
            if _cur != 0 and (_new == 0 or (_cur > 0 and _delta < 0) or (_cur < 0 and _delta > 0)):
                _closed_qty = min(abs(_cur), abs(_delta))
                _avg = float(_pos.get("avg_price", 0) or 0)
                _dir = 1 if _cur > 0 else -1
                _realized = _dir * (float(fill_price) - _avg) * _closed_qty
            if _new == 0:
                _ps["positions"].pop(sym, None)
            else:
                _pos["qty"] = _new
                if _cur == 0:
                    _pos["avg_price"] = float(fill_price)
                else:
                    _pos["avg_price"] = round(
                        (_cur * float(_pos.get("avg_price", 0)) + _delta * float(fill_price)) / _new, 2)
                _ps["positions"][sym] = _pos
            if _realized:
                _ps["realized_pnl"] = round(float(_ps.get("realized_pnl", 0) or 0) + _realized, 2)
            _ps_path.write_text(_j.dumps(_ps, indent=2, default=str), encoding="utf-8")
        except Exception as _se:
            logger.warning(f"paper_state sync failed: {_se}")

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

            # PHASE 6 FIX 2026-09-30: shared tick lookup for both DRY-RUN
            # and LIVE. The brain's CAS-long legs come through as MARKET
            # with price=0 — without this lookup, the paper client would
            # fall through to its "no chain, no tick" last-resort fill at
            # Rs.1.00. Instead, ask the core's tick store and use ask/bid.
            def _resolve_fill_price(o: Order) -> float:
                if o.price > 0:
                    return float(o.price)
                try:
                    r = self._http.get(f"{self.core_url}/api/state", timeout=3)
                    state = r.json()
                    ticks = state.get("ticks", {}) or {}
                    # Try symbol first, then underlying (CAS uses NIFTY
                    # cash symbol, but tick may be keyed as "NIFTY" too).
                    for candidate in (o.symbol, o.underlying):
                        tick = ticks.get(candidate) or {}
                        if tick:
                            if o.side.value == "BUY":
                                return float(tick.get("ask", 0) or tick.get("ltp", 0) or 0)
                            else:
                                return float(tick.get("bid", 0) or tick.get("ltp", 0) or 0)
                except Exception:
                    pass
                # FIX 2026-10-19: the core tick store lacks most option symbols,
                # so CLOSE orders (MARKET, price=0) fell through to the broker's
                # Rs.1.00 placeholder -> the EOD force-square realized a fake
                # -Rs.1,01,289 loss. Fall back to the fresh option-chain file
                # (real bid/ask) before giving up.
                _chain_fp = self._chain_fill_price(o)
                if _chain_fp > 0:
                    return _chain_fp
                return 0.0

            if self.dry_run:
                logger.info(f"[DRY-RUN] would place: {order.symbol} {order.side.value} {order.qty}")
                fill_price = _resolve_fill_price(order)
                # FIX 2026-10-21 (FAIL-CLOSED): never emit a fill at a
                # placeholder price (<=1.0) even in dry-run - it corrupts the
                # projection's avg_price and fabricates false P&L. Reject.
                if fill_price <= 1.0:
                    logger.warning(f"DRY-RUN: REJECT {order.symbol} - unresolvable fill price Rs.{fill_price}")
                    try:
                        self._http.post(
                            f"{self.core_url}/api/order_reject",
                            json={"order_id": client_order_id or eid,
                                  "reason": "unresolvable fill price (placeholder)"},
                            timeout=5,
                        )
                    except Exception:
                        pass
                    return
                if await self._post_fill(client_order_id or eid, fill_price, order.qty):
                    self._sync_paper_state({
                        "symbol": order.symbol, "side": order.side.value,
                        "client_order_id": client_order_id, "underlying": order.underlying,
                        "strike": order.strike, "option_type": order.option_type, "expiry": order.expiry,
                    }, fill_price, order.qty)
                return

            # LIVE path — fetch tick and turn MARKET into LIMIT @ tick.
            # PHASE 6 FIX 2026-09-30: if we have a tick from the core, post
            # the fill DIRECTLY to /api/order_fill and skip the legacy broker
            # entirely. The broker's paper client falls back to Rs.1.00
            # for cash-underlying symbols it can't price (NIFTY spot, etc.)
            # because its `self._ticks` only carries options. The core's tick
            # store (built from market.tick events) has the cash underlyings,
            # so we trust that as the source of truth.
            live_price = _resolve_fill_price(order)

            # FIX 2026-10-21 (FAIL-CLOSED): require a REAL price (>1.0), not
            # just >0. A 0.5 is still a placeholder and would corrupt avg_price.
            if live_price > 1.0:
                # Direct-fill path: we have a tick → emit fill event directly.
                # The order record is captured via ORDER_PROPOSED + ORDER_FILLED
                # events in the core's event log.
                if await self._post_fill(client_order_id or eid, live_price, order.qty):
                    logger.info(
                        f"DIRECT-FILL {order.symbol} {order.side.value} "
                        f"{order.qty} @ {live_price} (from core tick)"
                    )
                    self._sync_paper_state({
                        "symbol": order.symbol, "side": order.side.value,
                        "client_order_id": client_order_id, "underlying": order.underlying,
                        "strike": order.strike, "option_type": order.option_type, "expiry": order.expiry,
                    }, live_price, order.qty)
                    return
                # else: direct fill failed (core down?), fall through to broker path
                logger.warning(
                    f"direct fill failed for {order.symbol}; falling back to broker"
                )

            # Fallback: no tick available, try the legacy broker path
            # (it's the only way to fill orders for symbols we don't have
            # a core tick for, e.g. obscure weekly options).
            filled = broker.place_order(order)
            if filled.status.value in ("complete", "filled", "open"):
                # FIX 2026-10-16: the broker's paper_client falls back to
                # Rs.1.00 for symbols it can't price (cash underlyings, options
                # without a live tick). That placeholder was being posted to the
                # core, so every position's avg_price became 1.0 and realized
                # P&L was garbage. Resolve the REAL price from the fresh option
                # chain file (same source preflight uses) when the broker's fill
                # is a placeholder.
                _fp = float(filled.avg_fill_price or order.price or 0)
                if _fp <= 1.0:
                    _chain_fp = self._chain_fill_price(order)
                    if _chain_fp > 0:
                        _fp = _chain_fp
                # FIX 2026-10-21 (FAIL-CLOSED, not a patch): if the price is
                # STILL <=1.0 (placeholder), REJECT the order. Never fill at a
                # placeholder - a placeholder fill corrupts avg_price and
                # fabricates false P&L. Reject instead so the brain sees the
                # rejection and the queue is not poisoned.
                if _fp <= 1.0:
                    logger.warning(f"REJECT placeholder price Rs.{_fp} for {symbol} (cannot resolve real price); not filling")
                    try:
                        self._http.post(
                            f"{self.core_url}/api/order_reject",
                            json={"order_id": client_order_id or eid,
                                  "reason": "unresolvable fill price (placeholder)"},
                            timeout=5,
                        )
                    except Exception:
                        pass
                    return
                await self._post_fill(
                    client_order_id or eid,
                    _fp,
                    int(filled.qty),
                )
                logger.info(f"placed {symbol}: status={filled.status.value} fill={_fp}")
            else:
                logger.warning(f"order rejected: {filled.rejection_reason}")
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

    def _chain_fill_price(self, order) -> float:
        """Resolve a real fill price from the fresh option-chain file.

        The broker's paper_client returns Rs.1.00 for symbols it can't price
        (no live tick). The option chain file (data_cache/option_chain_<UND>.json,
        keys '<strike>_<CE|PE>') carries real bid/ask written fresh every cycle.
        Returns 0.0 if unresolvable so the caller keeps the broker's price.
        """
        try:
            import json as _json
            from pathlib import Path as _Path
            und = str(getattr(order, "underlying", "") or "NIFTY").upper()
            chain_path = _Path("data_cache") / f"option_chain_{und}.json"
            if not chain_path.exists():
                return 0.0
            data = _json.loads(chain_path.read_text(encoding="utf-8-sig"))
            strikes = data.get("strikes", {}) or {}
            sym = getattr(order, "symbol", "") or ""
            # FIX 2026-10-21 (ROOT CAUSE of today's placeholder fills): the
            # NIFTY CASH/spot leg (symbol == underlying, e.g. "NIFTY") is NOT
            # an option - it has no strike in the chain. The chain file carries
            # the real spot price in the "spot" field. Without this branch, a
            # NIFTY cash order found no strike -> returned 0.0 -> the broker
            # filled at Rs.1.00 placeholder (196 placeholder fills today vs 4
            # real). Use the chain's spot price for cash/spot orders.
            if sym.upper() == und or sym.upper() == f"{und}SPOT":
                _spot = float(data.get("spot", 0) or 0)
                if _spot > 1.0:
                    return _spot
                return 0.0
            # chain keys are '<strike>_<CE|PE>'; bridge symbol is NIFTY<exp><strike><CE|PE>.
            # Match against the ACTUAL chain keys (robust vs regex, which grabs
            # the expiry digits too, e.g. '622900' instead of '22900').
            key = None
            if sym in strikes:
                key = sym
            else:
                _opt = "CE" if sym.endswith("CE") else ("PE" if sym.endswith("PE") else "")
                if _opt:
                    for _ck in strikes:
                        if _ck.endswith(f"_{_opt}") and sym.endswith(_ck.replace("_", "")):
                            key = _ck
                            break
            if key is None or key not in strikes:
                return 0.0
            s = strikes[key]
            bid = float(s.get("bid", 0) or 0)
            ask = float(s.get("ask", 0) or 0)
            side = str(getattr(order, "side", "") or "").upper()
            if side == "BUY":
                return ask if ask > 0 else (bid if bid > 0 else 0.0)
            return bid if bid > 0 else (ask if ask > 0 else 0.0)
        except Exception:
            return 0.0

    def _sync_full_from_core(self) -> None:
        """FIX 2026-10-19 (ROOT CAUSE): the bot no longer writes paper_state.json
        in bridge-active mode, so the gateway is the SOLE writer. It must sync
        the FULL state from the core (positions + realized P&L), not just on
        fills - otherwise closes and EOD squares never reach paper_state.json
        and the dashboard/journal/survival go stale. The core is the source of
        truth; paper_state.json is a derived view of it.
        """
        try:
            import json as _j
            from pathlib import Path as _P
            _ps_path = _P(self.paper_state_path)
            _ps = {}
            if _ps_path.exists():
                try:
                    _ps = _j.loads(_ps_path.read_text(encoding="utf-8-sig"))
                except Exception:
                    _ps = {}
            _ps.setdefault("orders", {})
            _ps.setdefault("positions", {})
            # positions from core
            _r = self._http.get(f"{self.core_url}/api/positions", timeout=5)
            _core = _r.json().get("positions", {}) or {}
            _new_pos = {}
            for _sym, _p in _core.items():
                if isinstance(_p, dict) and _p.get("qty"):
                    _new_pos[_sym] = {
                        "symbol": _sym, "qty": _p.get("qty"),
                        "avg_price": _p.get("avg_price", 0),
                        "ltp": _p.get("ltp", 0),
                        "pnl": _p.get("pnl", 0) or 0,
                        "expiry": _p.get("expiry", ""),
                    }
            _ps["positions"] = _new_pos
            # realized P&L + cash from core state (under 'account')
            try:
                _rs = self._http.get(f"{self.core_url}/api/state", timeout=5).json()
                _acct = _rs.get("account", {}) or {}
                _rp = _acct.get("realized_pnl", _ps.get("realized_pnl", 0))
                _cash = _acct.get("cash", _ps.get("cash", 100000))
                _ps["realized_pnl"] = _rp
                _ps["cash"] = _cash
            except Exception:
                pass
            _ps_path.write_text(_j.dumps(_ps, indent=2, default=str), encoding="utf-8")
        except Exception as _se:
            logger.warning(f"full paper_state sync failed: {_se}")

    async def run_forever(self):
        """Subscribe to /ws, process order events forever."""
        # PHASE 6 FIX 2026-09-30: per-service heartbeat. Lets the
        # 247_watchdog detect a stuck gateway (alive process but no fills).
        from ..common.heartbeat import HeartbeatWriter
        hb = HeartbeatWriter("exec_gateway", interval_sec=10)
        hb.update(ws_connected=False, fills=0, rejects=0, dry_run=self.dry_run)
        hb.start()

        ws_uri = self.core_url.replace("http://", "ws://") + "/ws"
        backoff = 1.0
        while True:
            try:
                logger.info(f"connecting to {ws_uri}...")
                async with websockets.connect(ws_uri) as ws:
                    logger.info(f"connected: {ws_uri}")
                    backoff = 1.0
                    hb.update(ws_connected=True)
                    # First message is snapshot; drain it
                    await ws.recv()
                    # Then process events
                    _last_full_sync = 0.0
                    while True:
                        try:
                            # FIX 2026-10-19: periodic full sync from core on a
                            # TIMER, NOT gated behind ws.recv(). If placed after
                            # recv(), it only runs when a message arrives - with
                            # no orders coming, paper_state never syncs. Use
                            # asyncio.wait_for so the sync fires even when the
                            # socket is idle.
                            if time.time() - _last_full_sync > 30:
                                _last_full_sync = time.time()
                                self._sync_full_from_core()
                            try:
                                msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                            except asyncio.TimeoutError:
                                continue  # no message; loop back to check sync timer
                            data = json.loads(msg)
                            if data.get("type") == "events":
                                for event in data.get("data", []):
                                    if event.get("type") == "order.proposed":
                                        await self._handle_order_event(event)
                                        hb.update(
                                            ws_connected=True,
                                            fills=len(self.processed_orders),
                                        )
                        except Exception as inner:
                            logger.warning(f"inner error: {inner}")
                            hb.update(last_error=str(inner)[:200])
                            break
            except Exception as e:
                logger.error(f"WS connection failed: {e}, retrying in {backoff}s")
                hb.update(ws_connected=False, last_error=str(e)[:200])
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