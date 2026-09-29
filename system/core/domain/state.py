"""State projections — derive current state from event log.

The current state of the trading system is a fold of all events. This file
defines the projections we expose to the rest of the system (UI, brain, exec).

Projections are NOT stored as separate state — they're computed on demand
from the event log. This is the heart of event-sourcing.

Tradeoffs:
- Pro: Impossible to have inconsistent state. The event log IS the truth.
- Pro: Easy to add new projections without changing writes.
- Con: Slower reads than denormalized tables. Mitigated by:
  - SQLite is fast enough for paper trading
  - For high-frequency reads (UI), maintain a small in-memory snapshot
    that gets invalidated on every event.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .events import Event, EventType


@dataclass
class Position:
    symbol: str
    underlying: str
    qty: int = 0
    avg_price: float = 0.0
    ltp: float = 0.0
    strike: float = 0.0
    option_type: str = ""
    expiry: str = ""
    exchange: str = "NFO"
    product: str = "MIS"
    opened_at: str = ""
    pnl: float = 0.0


@dataclass
class Order:
    order_id: str
    broker_order_id: str = ""
    client_order_id: str = ""
    symbol: str = ""
    underlying: str = ""
    side: str = ""
    qty: int = 0
    filled_qty: int = 0
    order_type: str = "MARKET"
    product: str = "MIS"
    price: float = 0.0
    avg_fill_price: float = 0.0
    status: str = "PROPOSED"
    tag: str = ""
    strike: float = 0.0
    option_type: str = ""
    expiry: str = ""
    exchange: str = "NFO"
    placed_at: str = ""
    filled_at: str = ""
    rejection_reason: str = ""
    plan_id: str = ""


@dataclass
class Plan:
    plan_id: str
    strategy: str
    underlying: str
    legs: list
    target: float = 0.0
    stop: float = 0.0
    confidence: float = 0.0
    reason: str = ""
    opened_at: str = ""
    closed_at: str = ""
    status: str = "PROPOSED"  # PROPOSED | EXECUTING | COMPLETED | FAILED | CANCELLED


@dataclass
class AccountState:
    cash: float = 100000.0
    starting_capital: float = 100000.0
    realized_pnl: float = 0.0
    is_paused: bool = False
    pause_reason: str = ""


@dataclass
class Tick:
    symbol: str
    ltp: float = 0.0
    bid: float = 0.0
    ask: float = 0.0
    oi: int = 0
    volume: int = 0
    ts: str = ""


class StateProjection:
    """Computes current state by folding events."""

    def __init__(self):
        self.account = AccountState()
        self.positions: dict[str, Position] = {}
        self.orders: dict[str, Order] = {}
        self.plans: dict[str, Plan] = {}
        self.ticks: dict[str, Tick] = {}
        self.rejected_orders: list[dict] = []
        self.risk_breaches: list[dict] = []
        self.last_plan_id: str = ""
        self.last_brain_decision_ts: str = ""

    def apply(self, event: Event) -> None:
        """Apply an event to update the projection."""
        et = event.type
        p = event.payload

        if et == EventType.SESSION_STARTED:
            pass
        elif et == EventType.SESSION_ENDED:
            self.account.is_paused = True

        elif et == EventType.ORDER_PROPOSED:
            client_oid = p.get("client_order_id") or f"co-{event.id}"
            self.orders[client_oid] = Order(
                order_id=client_oid,
                client_order_id=client_oid,
                symbol=p.get("symbol", ""),
                underlying=p.get("underlying", ""),
                side=p.get("side", ""),
                qty=int(p.get("qty", 0)),
                order_type=p.get("order_type", "MARKET"),
                product=p.get("product", "MIS"),
                price=float(p.get("price", 0) or 0),
                tag=p.get("tag", ""),
                strike=float(p.get("strike", 0) or 0),
                option_type=p.get("option_type", ""),
                expiry=p.get("expiry", ""),
                exchange=p.get("exchange", "NFO"),
                plan_id=event.correlation_id,
            )

        elif et == EventType.ORDER_REJECTED:
            self.rejected_orders.append({
                "ts": event.ts,
                "order": p.get("order", {}),
                "reason": p.get("reason", ""),
                "gate": p.get("gate", ""),
                "actor": event.actor,
            })

        elif et == EventType.ORDER_PLACED:
            client_oid = p["order"].get("client_order_id") or p.get("broker_order_id", "")
            broker_oid = p.get("broker_order_id", "")
            if client_oid in self.orders:
                self.orders[client_oid].broker_order_id = broker_oid
                self.orders[client_oid].status = "PLACED"
                self.orders[client_oid].placed_at = event.ts
            else:
                # Synthetic record (broker placed directly, e.g. legacy path)
                self.orders[client_oid] = Order(
                    order_id=client_oid,
                    broker_order_id=broker_oid,
                    client_order_id=client_oid,
                    symbol=p["order"].get("symbol", ""),
                    underlying=p["order"].get("underlying", ""),
                    side=p["order"].get("side", ""),
                    qty=int(p["order"].get("qty", 0)),
                    status="PLACED",
                    placed_at=event.ts,
                )

        elif et == EventType.ORDER_FILLED:
            broker_oid = p.get("order_id", "")
            client_oid = self._find_client_by_broker(broker_oid)
            target = client_oid or broker_oid
            if target and target in self.orders:
                o = self.orders[target]
                if "fill_price" in p:
                    o.avg_fill_price = float(p["fill_price"])
                if "filled_qty" in p:
                    o.filled_qty = int(p["filled_qty"])
                o.status = "FILLED"
                o.filled_at = event.ts
            if "fill_price" in p and "filled_qty" in p:
                self._apply_fill_to_position(p)

        elif et == EventType.ORDER_CANCELLED:
            for o in self.orders.values():
                if o.broker_order_id == p.get("order_id") or o.order_id == p.get("order_id"):
                    o.status = "CANCELLED"

        elif et == EventType.PLAN_SUBMITTED:
            pid = event.correlation_id or p.get("plan_id", "")
            self.plans[pid] = Plan(
                plan_id=pid,
                strategy=p.get("strategy", ""),
                underlying=p.get("underlying", ""),
                legs=p.get("legs", []),
                target=float(p.get("target", 0) or 0),
                stop=float(p.get("stop", 0) or 0),
                confidence=float(p.get("confidence", 0) or 0),
                reason=p.get("reason", ""),
                opened_at=event.ts,
                status="EXECUTING",
            )
            self.last_plan_id = pid

        elif et == EventType.PLAN_COMPLETED:
            pid = event.correlation_id
            if pid in self.plans:
                self.plans[pid].status = "COMPLETED"

        elif et == EventType.PLAN_FAILED:
            pid = event.correlation_id
            if pid in self.plans:
                self.plans[pid].status = "FAILED"
                self.plans[pid].closed_at = event.ts

        elif et == EventType.RISK_LIMIT_BREACHED:
            self.risk_breaches.append({
                "ts": event.ts,
                "limit_name": p.get("limit_name", ""),
                "value": p.get("value", 0),
                "threshold": p.get("threshold", 0),
            })

        elif et == EventType.RISK_CIRCUIT_BREAKER:
            self.account.is_paused = True
            self.account.pause_reason = p.get("reason", "circuit_breaker")

        elif et == EventType.AUDIT_LOG:
            # FIX 2026-09-29 21:30: store audit entries for /api/audit endpoint
            if not hasattr(self, "audit_entries"):
                self.audit_entries = []
            self.audit_entries.append({
                "ts": event.ts,
                "action": p.get("action", ""),
                "actor": event.actor,
                "details": p.get("details", {}),
            })
            # Keep last 100
            self.audit_entries = self.audit_entries[-100:]

        elif et == EventType.MARKET_TICK:
            sym = p.get("symbol", "")
            if not sym:
                return  # skip malformed tick
            # FIX 2026-09-29 21:15: defensive .get() — previous code did p["ltp"] which
            # raised KeyError on any tick with missing field, crashing the core.
            self.ticks[sym] = Tick(
                symbol=sym,
                ltp=float(p.get("ltp", 0) or 0),
                bid=float(p.get("bid", 0) or 0),
                ask=float(p.get("ask", 0) or 0),
                oi=int(p.get("oi", 0) or 0),
                volume=int(p.get("volume", 0) or 0),
                ts=event.ts,
            )
            if sym in self.positions:
                pos = self.positions[sym]
                pos.ltp = float(p.get("ltp", 0) or 0)
                pos.pnl = (pos.ltp - pos.avg_price) * pos.qty

    def _find_client_by_broker(self, broker_oid: str) -> Optional[str]:
        for coid, o in self.orders.items():
            if o.broker_order_id == broker_oid:
                return coid
        return None

    def _apply_fill_to_position(self, fill_payload: dict) -> None:
        """Update position projection from an ORDER_FILLED event.

        Handles both:
        1. Fills with a known order_id — look up order, apply delta
        2. Orphan fills (e.g. legacy bot bridging) — use synthetic symbol/qty from payload
        """
        oid = fill_payload.get("order_id", "")
        client_oid = self._find_client_by_broker(oid) if oid else None
        if client_oid and client_oid in self.orders:
            o = self.orders[client_oid]
            sym = o.symbol
            side = o.side.upper()
        else:
            # FIX 2026-09-29 21:35: orphan fill (no matching order).
            # Use synthetic symbol/qty/side from payload. This is how the
            # legacy bot's positions enter the event log.
            sym = fill_payload.get("symbol") or (oid.replace("legacy-", "") if oid.startswith("legacy-") else "UNKNOWN")
            side = fill_payload.get("side", "BUY")
        qty = int(fill_payload["filled_qty"])
        fill_price = float(fill_payload["fill_price"])

        # Get underlying attributes from order (or defaults for orphan fills)
        _und = o.underlying if 'o' in locals() and o else fill_payload.get("underlying", "")
        _strike = o.strike if 'o' in locals() and o else 0.0
        _opt = o.option_type if 'o' in locals() and o else ""
        _exp = o.expiry if 'o' in locals() and o else ""
        _exch = o.exchange if 'o' in locals() and o else "NFO"
        _prod = o.product if 'o' in locals() and o else "MIS"

        if sym not in self.positions:
            self.positions[sym] = Position(
                symbol=sym,
                underlying=_und,
                qty=0,
                avg_price=0.0,
                ltp=fill_price,
                strike=_strike,
                option_type=_opt,
                expiry=_exp,
                exchange=_exch,
                product=_prod,
                opened_at=fill_payload.get("ts", ""),
            )

        pos = self.positions[sym]
        if side == "BUY":
            new_qty = pos.qty + qty
            if new_qty > 0 and pos.qty >= 0:
                # Adding to long or opening long
                pos.avg_price = (
                    (pos.avg_price * pos.qty) + (fill_price * qty)
                ) / new_qty if new_qty else 0.0
            elif new_qty > 0 and pos.qty < 0:
                # Covering short
                if qty >= abs(pos.qty):
                    pos.avg_price = fill_price
                else:
                    pos.avg_price = pos.avg_price
            pos.qty = new_qty
        else:  # SELL
            new_qty = pos.qty - qty
            if pos.qty > 0 and new_qty >= 0:
                # Selling long
                pass
            elif pos.qty > 0 and new_qty < 0:
                # Flipping to short
                pos.avg_price = fill_price
            elif pos.qty < 0:
                # Adding to short
                pos.avg_price = (
                    (pos.avg_price * abs(pos.qty)) + (fill_price * qty)
                ) / abs(new_qty) if abs(new_qty) else 0.0
            pos.qty = new_qty

        if pos.qty == 0:
            # Position closed
            self.account.realized_pnl += (fill_price - pos.avg_price) * (qty if side == "SELL" else -qty)

        pos.pnl = (fill_price - pos.avg_price) * pos.qty if pos.qty else 0.0

    def snapshot(self) -> dict:
        """Serialize current state for API responses."""
        return {
            "ts": self.last_brain_decision_ts,
            "account": {
                "cash": self.account.cash,
                "starting_capital": self.account.starting_capital,
                "realized_pnl": self.account.realized_pnl,
                "is_paused": self.account.is_paused,
                "pause_reason": self.account.pause_reason,
            },
            "positions": {sym: vars(p) for sym, p in self.positions.items() if p.qty != 0},
            "open_orders": [vars(o) for o in self.orders.values() if o.status in ("PROPOSED", "PLACED")],
            "open_plans": [vars(p) for p in self.plans.values() if p.status in ("EXECUTING", "PROPOSED")],
            "recent_rejections": self.rejected_orders[-10:],
            "risk_breaches_today": len(self.risk_breaches),
            "ticks_known": len(self.ticks),
        }