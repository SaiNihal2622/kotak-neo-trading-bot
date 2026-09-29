"""FastAPI server — the public API of the trading core.

Endpoints:
- GET /api/state                    Current state snapshot
- GET /api/positions                Open positions
- GET /api/orders                   Recent orders
- GET /api/audit                    Audit log
- GET /api/events                   Event log (paginated)
- POST /api/plan                    Submit a multi-leg plan (atomic)
- POST /api/order                   Submit a single order
- POST /api/cancel/{order_id}       Cancel an order
- POST /api/close_all               Close all positions
- POST /api/force_action            Force action (pause/resume/etc)
- GET /api/metrics                  Prometheus metrics
- WS  /ws                           Real-time event stream
- GET /healthz                      Health check

The API is the ONLY public interface to the system. All writes go through
POST endpoints that:
1. Validate via pre-flight
2. Emit events (in a transaction)
3. Return the new state
"""
from __future__ import annotations

import asyncio
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, validator

from ..domain.events import (
    Event, EventType,
    order_proposed, order_validated, order_rejected, order_placed, order_filled,
    order_cancelled,
    plan_submitted, plan_completed, plan_failed,
    risk_limit_breached, risk_circuit_breaker,
    market_tick,
)
from ..domain.state import StateProjection
from ..store.event_store import EventStore
from ..risk.preflight import PreFlight, PreflightResult


# ----- Pydantic schemas (API contracts) -----

class OrderSchema(BaseModel):
    client_order_id: str = ""
    symbol: str
    underlying: str = "NIFTY"
    side: str = Field(..., pattern="^(BUY|SELL)$")
    qty: int = Field(..., gt=0)
    order_type: str = "MARKET"
    product: str = "MIS"
    price: float = 0.0
    tag: str = ""
    strike: float = 0.0
    option_type: str = ""
    expiry: str = ""
    exchange: str = "NFO"
    plan_id: str = ""

    @validator("client_order_id", always=True)
    def default_client_id(cls, v):
        import uuid
        return v or f"co-{uuid.uuid4().hex[:12]}"


class PlanSchema(BaseModel):
    strategy: str
    underlying: str = "NIFTY"
    legs: list[OrderSchema]
    target: float = 0.0
    stop: float = 0.0
    confidence: float = 0.0
    reason: str = ""
    dry_run: bool = True  # paper by default


class ForceActionSchema(BaseModel):
    action: str = Field(..., pattern="^(PAUSE|RESUME|CLOSE_ALL|RESET|RELOAD_BRAIN)$")
    reason: str = ""


# ----- App factory -----

def create_app(db_path: str = "data_cache/state.db") -> FastAPI:
    app = FastAPI(title="Kotak Trading Core", version="1.0.0")

    # Initialize state
    app.state.store = EventStore(db_path)
    app.state.projection = app.state.store.build_state_projection()
    app.state.preflight = PreFlight()
    app.state.ws_clients = set()
    # FIX 2026-09-29 21:15: use asyncio.Lock (async-safe) instead of threading.Lock.
    # A threading lock inside async code blocks the event loop, stalling all other
    # coroutines (including health checks and other HTTP requests).
    import asyncio as _asyncio
    app.state.ws_lock = _asyncio.Lock()

    # ----- Health & introspection -----

    @app.get("/healthz")
    async def healthz():
        # FIX 2026-09-29 21:15: actually count events in the log instead of returning null.
        # Use a cheap query that doesn't load events into memory.
        count = app.state.store._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        return {
            "ok": True,
            "ts": datetime.utcnow().isoformat(),
            "events_in_log": count,
        }

    @app.get("/api/state")
    async def get_state():
        return app.state.projection.snapshot()

    @app.get("/api/positions")
    async def get_positions():
        return {
            "positions": {sym: vars(p) for sym, p in app.state.projection.positions.items() if p.qty != 0},
        }

    @app.get("/api/orders")
    async def get_orders(limit: int = 100):
        orders = list(app.state.projection.orders.values())
        orders.sort(key=lambda o: o.placed_at, reverse=True)
        return {"orders": [vars(o) for o in orders[:limit]]}

    @app.get("/api/audit")
    async def get_audit(limit: int = 100):
        rows = app.state.store._conn.execute(
            "SELECT ts, actor, action, details_json FROM audit_log ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return {
            "audit": [
                {"ts": r[0], "actor": r[1], "action": r[2], "details": json.loads(r[3])}
                for r in rows
            ]
        }

    @app.get("/api/events")
    async def get_events(types: str = "", limit: int = 100):
        type_list = []
        if types:
            type_list = [EventType(t) for t in types.split(",") if t]
        events = app.state.store.events_since(types=type_list or None, limit=limit)
        return {
            "events": [
                {"id": e.id, "ts": e.ts, "type": e.type.value, "actor": e.actor,
                 "correlation_id": e.correlation_id, "payload": e.payload}
                for e in events
            ]
        }

    # ----- Submit operations (with pre-flight) -----

    @app.post("/api/plan")
    async def submit_plan(plan: PlanSchema):
        """Submit a multi-leg plan. Atomic — all legs pass pre-flight or none."""
        plan_dict = plan.dict()
        result = app.state.preflight.check_plan(plan_dict, app.state.projection)
        if not result.ok:
            # Reject: emit ORDER_REJECTED events for each leg
            events_to_emit = []
            for leg in plan_dict["legs"]:
                events_to_emit.append(order_rejected(leg, result.reason, result.gate))
            app.state.store.append_batch(events_to_emit)
            await _broadcast(app, events_to_emit)
            return JSONResponse(status_code=400, content={"error": result.to_dict()})

        # Validate: emit PLAN_SUBMITTED + ORDER_PROPOSED for each leg
        events_to_emit = [
            plan_submitted(plan_dict, actor=plan_dict.get("actor", "brain")),
        ]
        for leg in plan_dict["legs"]:
            events_to_emit.append(order_proposed(leg, actor="brain", correlation_id=events_to_emit[0].correlation_id))
            events_to_emit.append(order_validated(leg["client_order_id"], correlation_id=events_to_emit[0].correlation_id))
        app.state.store.append_batch(events_to_emit)
        for e in events_to_emit:
            app.state.projection.apply(e)
        await _broadcast(app, events_to_emit)
        return {
            "ok": True,
            "plan_id": events_to_emit[0].correlation_id,
            "legs": len(plan_dict["legs"]),
            "dry_run": plan.dry_run,
        }

    @app.post("/api/order")
    async def submit_order(order: OrderSchema):
        """Submit a single order. Pre-flight validated."""
        order_dict = order.dict()
        result = app.state.preflight.check_order(order_dict, app.state.projection)
        if not result.ok:
            event = order_rejected(order_dict, result.reason, result.gate)
            app.state.store.append(event)
            app.state.projection.apply(event)
            await _broadcast(app, [event])
            return JSONResponse(status_code=400, content={"error": result.to_dict()})

        events = [
            order_proposed(order_dict),
            order_validated(order_dict["client_order_id"]),
        ]
        app.state.store.append_batch(events)
        for e in events:
            app.state.projection.apply(e)
        await _broadcast(app, events)
        return {
            "ok": True,
            "client_order_id": order_dict["client_order_id"],
        }

    @app.post("/api/cancel/{order_id}")
    async def cancel_order(order_id: str):
        event = order_cancelled_payload(order_id)
        app.state.store.append(event)
        app.state.projection.apply(event)
        await _broadcast(app, [event])
        return {"ok": True}

    @app.post("/api/close_all")
    async def close_all():
        positions = [p for p in app.state.projection.positions.values() if p.qty != 0]
        if not positions:
            return {"ok": True, "closed": 0}

        events = []
        for pos in positions:
            close_side = "SELL" if pos.qty > 0 else "BUY"
            close_qty = abs(pos.qty)
            client_oid = f"close-{pos.symbol}-{datetime.utcnow().timestamp()}"
            events.append(order_proposed({
                "client_order_id": client_oid,
                "symbol": pos.symbol,
                "underlying": pos.underlying,
                "side": close_side,
                "qty": close_qty,
                "order_type": "MARKET",
                "tag": "FORCE-CLOSE-ALL",
                "exchange": pos.exchange,
                "strike": pos.strike,
                "option_type": pos.option_type,
                "expiry": pos.expiry,
            }))
            events.append(order_validated(client_oid))
        app.state.store.append_batch(events)
        for e in events:
            app.state.projection.apply(e)
        app.state.store.audit(actor="api", action="CLOSE_ALL", details={"count": len(positions)})
        await _broadcast(app, events)
        return {"ok": True, "closed": len(positions)}

    @app.post("/api/force_action")
    async def force_action(action: ForceActionSchema):
        details = {"action": action.action, "reason": action.reason}
        if action.action == "PAUSE":
            from ..domain.events import risk_circuit_breaker as _rcb
            event = _rcb(action.reason or "manual_pause")
            app.state.store.append(event)
            app.state.projection.apply(event)
        elif action.action == "RESUME":
            # Direct state reset (not via event for now)
            app.state.projection.account.is_paused = False
            app.state.projection.account.pause_reason = ""
        elif action.action == "RESET":
            # Truncate event log (DANGEROUS — paper only)
            with app.state.store._lock:
                app.state.store._conn.execute("DELETE FROM events")
                app.state.store._conn.execute("DELETE FROM snapshot")
                app.state.store._conn.commit()
            app.state.projection = StateProjection()
        app.state.store.audit(actor="api", action=action.action, details=details)
        return {"ok": True, "details": details}

    @app.post("/api/market_tick")
    async def post_tick(symbol: str, ltp: float, bid: float, ask: float, oi: int = 0, volume: int = 0):
        """Inject a market tick (from data feed or paper)."""
        event = market_tick(symbol, ltp, bid, ask, oi, volume)
        app.state.store.append(event)
        app.state.projection.apply(event)
        await _broadcast(app, [event])
        return {"ok": True}

    # ----- WebSocket for real-time updates -----

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        # FIX 2026-09-29 21:15: use async lock
        async with app.state.ws_lock:
            app.state.ws_clients.add(websocket)
        try:
            # Send initial state
            await websocket.send_json({"type": "snapshot", "data": app.state.projection.snapshot()})
            # Then keep alive
            while True:
                msg = await websocket.receive_text()
                if msg == "ping":
                    await websocket.send_text("pong")
        except WebSocketDisconnect:
            pass
        finally:
            async with app.state.ws_lock:
                app.state.ws_clients.discard(websocket)

    # ----- Prometheus metrics -----

    @app.get("/api/metrics")
    async def metrics():
        # Minimal Prometheus exposition. Real implementation would track
        # pnl, position count, fill rate, etc. via prometheus_client.
        proj = app.state.projection
        lines = [
            "# HELP kotak_positions_count Number of open positions",
            "# TYPE kotak_positions_count gauge",
            f"kotak_positions_count {len(proj.positions)}",
            "# HELP kotak_cash Available cash",
            "# TYPE kotak_cash gauge",
            f"kotak_cash {proj.account.cash}",
            "# HELP kotak_realized_pnl Realized PnL",
            "# TYPE kotak_realized_pnl gauge",
            f"kotak_realized_pnl {proj.account.realized_pnl}",
            "# HELP kotak_is_paused Bot paused flag",
            "# TYPE kotak_is_paused gauge",
            f"kotak_is_paused {1 if proj.account.is_paused else 0}",
            "# HELP kotak_rejections_total Total rejected orders",
            "# TYPE kotak_rejections_total counter",
            f"kotak_rejections_total {len(proj.rejected_orders)}",
            "# HELP kotak_risk_breaches_total Total risk limit breaches",
            "# TYPE kotak_risk_breaches_total counter",
            f"kotak_risk_breaches_total {len(proj.risk_breaches)}",
        ]
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse("\n".join(lines), media_type="text/plain")

    return app


def order_cancelled_payload(order_id: str) -> Event:
    return order_cancelled(order_id)


async def _broadcast(app: FastAPI, events: list[Event]) -> None:
    """Push events to all WebSocket subscribers."""
    payload = {"type": "events", "data": [
        {"id": e.id, "ts": e.ts, "type": e.type.value, "actor": e.actor,
         "correlation_id": e.correlation_id, "payload": e.payload}
        for e in events
    ]}
    # FIX 2026-09-29 21:15: use async lock so concurrent broadcasts don't race.
    # Snapshot the client set under the lock to avoid holding it during awaits.
    async with app.state.ws_lock:
        clients = list(app.state.ws_clients)
    # Send to each client outside the lock; a slow client only stalls itself.
    dead = []
    for ws in clients:
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    if dead:
        async with app.state.ws_lock:
            for ws in dead:
                app.state.ws_clients.discard(ws)


# ----- Runner -----

if __name__ == "__main__":
    import uvicorn
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data_cache/state.db")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8510)
    args = parser.parse_args()
    app = create_app(args.db)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")