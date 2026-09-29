"""Event-sourced domain events for the trading core.

Every state change in the system is an immutable event. The current state
is the fold (reduce) of all events. This is the foundation of the rewrite
because:

1. Order placement = one OrderPlaced event. Fill = OrderFilled event.
2. State updates happen INSIDE transactions, never via file polling.
3. Audit trail is free (every event has ts + actor).

Events are stored in the `events` table with:
- id: BIGSERIAL PK
- ts: ISO timestamp
- type: event type (string)
- actor: who/what caused this (e.g. "brain:claude-3", "exec:paper")
- payload_json: the event payload (JSON)
- correlation_id: for tying related events together (e.g. all legs of a plan)
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any
import json
import uuid


class EventType(str, Enum):
    # Session
    SESSION_STARTED = "session.started"
    SESSION_ENDED = "session.ended"

    # Orders
    ORDER_PROPOSED = "order.proposed"      # LLM/brain proposes
    ORDER_VALIDATED = "order.validated"    # pre-flight passed
    ORDER_REJECTED = "order.rejected"      # pre-flight failed (reason captured)
    ORDER_PLACED = "order.placed"          # sent to broker
    ORDER_FILLED = "order.filled"          # broker confirms fill
    ORDER_CANCELLED = "order.cancelled"
    ORDER_EXPIRED = "order.expired"

    # Plans (multi-leg strategies)
    PLAN_SUBMITTED = "plan.submitted"      # atomic plan
    PLAN_EXECUTING = "plan.executing"      # some legs filled
    PLAN_COMPLETED = "plan.completed"   # all legs filled
    PLAN_FAILED = "plan.failed"            # any leg rejected → rollback
    PLAN_CANCELLED = "plan.cancelled"

    # Positions (derived from orders)
    POSITION_OPENED = "position.opened"
    POSITION_CHANGED = "position.changed"
    POSITION_CLOSED = "position.closed"

    # Risk
    RISK_LIMIT_BREACHED = "risk.limit_breached"
    RISK_CIRCUIT_BREAKER = "risk.circuit_breaker"

    # Brain
    BRAIN_DECISION_REQUESTED = "brain.decision_requested"
    BRAIN_DECISION_PROVIDED = "brain.decision_provided"

    # Market
    MARKET_TICK = "market.tick"
    MARKET_REGIME_CHANGE = "market.regime_change"

    # Audit
    AUDIT_FORCE_ACTION = "audit.force_action"
    AUDIT_LOG = "audit.log"                # FIX 2026-09-29 21:30: replaces direct audit_log writes


@dataclass
class Event:
    """Immutable event record."""
    type: EventType
    actor: str
    payload: dict
    correlation_id: str = ""
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])

    def to_row(self) -> dict:
        """Serialize for SQLite insert."""
        return {
            "id": self.id,
            "ts": self.ts,
            "type": self.type.value,
            "actor": self.actor,
            "correlation_id": self.correlation_id,
            "payload_json": json.dumps(self.payload, default=str),
        }

    @classmethod
    def from_row(cls, row: dict) -> "Event":
        return cls(
            id=row["id"],
            ts=row["ts"],
            type=EventType(row["type"]),
            actor=row["actor"],
            correlation_id=row.get("correlation_id", ""),
            payload=json.loads(row["payload_json"]),
        )


# ----- Convenience constructors for common events -----

def order_proposed(order: dict, actor: str = "brain", correlation_id: str = "") -> Event:
    return Event(
        type=EventType.ORDER_PROPOSED,
        actor=actor,
        payload=order,
        correlation_id=correlation_id,
    )


def order_validated(order_id: str, correlation_id: str = "") -> Event:
    return Event(
        type=EventType.ORDER_VALIDATED,
        actor="risk",
        payload={"order_id": order_id},
        correlation_id=correlation_id,
    )


def order_rejected(order: dict, reason: str, gate: str, actor: str = "risk") -> Event:
    return Event(
        type=EventType.ORDER_REJECTED,
        actor=actor,
        payload={"order": order, "reason": reason, "gate": gate},
    )


def order_placed(order: dict, broker_order_id: str, actor: str = "exec") -> Event:
    return Event(
        type=EventType.ORDER_PLACED,
        actor=actor,
        payload={"order": order, "broker_order_id": broker_order_id},
        correlation_id=order.get("client_order_id", ""),
    )


def order_filled(
    order_id: str,
    fill_price: float,
    filled_qty: int,
    slippage_bps: float = 0.0,
    symbol: str = None,
    side: str = None,
) -> Event:
    """FIX 2026-09-29 21:35: symbol/side are optional — for orphan fills
    (no matching order in the event log, e.g. legacy bot bridging).
    """
    payload = {
        "order_id": order_id,
        "fill_price": fill_price,
        "filled_qty": filled_qty,
        "slippage_bps": slippage_bps,
    }
    if symbol:
        payload["symbol"] = symbol
    if side:
        payload["side"] = side
    return Event(
        type=EventType.ORDER_FILLED,
        actor="broker",
        payload=payload,
    )


def plan_submitted(plan: dict, actor: str = "brain") -> Event:
    cid = plan.get("plan_id", uuid.uuid4().hex[:12])
    plan["plan_id"] = cid
    return Event(
        type=EventType.PLAN_SUBMITTED,
        actor=actor,
        payload=plan,
        correlation_id=cid,
    )


def plan_completed(plan_id: str, fills: list, actor: str = "exec") -> Event:
    return Event(
        type=EventType.PLAN_COMPLETED,
        actor=actor,
        payload={"plan_id": plan_id, "fills": fills},
        correlation_id=plan_id,
    )


def plan_failed(plan_id: str, reason: str, filled_legs: list, actor: str = "exec") -> Event:
    return Event(
        type=EventType.PLAN_FAILED,
        actor=actor,
        payload={"plan_id": plan_id, "reason": reason, "filled_legs": filled_legs},
        correlation_id=plan_id,
    )


def risk_limit_breached(limit_name: str, value: float, threshold: float, actor: str = "risk") -> Event:
    return Event(
        type=EventType.RISK_LIMIT_BREACHED,
        actor=actor,
        payload={"limit_name": limit_name, "value": value, "threshold": threshold},
    )


def risk_circuit_breaker(reason: str, drawdown_pct: float = 0.0, actor: str = "risk") -> Event:
    return Event(
        type=EventType.RISK_CIRCUIT_BREAKER,
        actor=actor,
        payload={"reason": reason, "drawdown_pct": drawdown_pct},
    )


def market_tick(symbol: str, ltp: float, bid: float, ask: float, oi: int = 0, volume: int = 0) -> Event:
    return Event(
        type=EventType.MARKET_TICK,
        actor="data",
        payload={"symbol": symbol, "ltp": ltp, "bid": bid, "ask": ask, "oi": oi, "volume": volume},
    )


def order_cancelled(order_id: str, actor: str = "exec") -> Event:
    return Event(
        type=EventType.ORDER_CANCELLED,
        actor=actor,
        payload={"order_id": order_id},
        correlation_id=order_id,
    )


def audit_log(action: str, actor: str, details: dict = None) -> Event:
    """FIX 2026-09-29 21:30: replaces direct audit_log table writes.

    Use this for any admin / force / override action so the audit trail
    is captured in the event log (replayable, queryable, consistent
    with the rest of the state).
    """
    return Event(
        type=EventType.AUDIT_LOG,
        actor=actor,
        payload={"action": action, "details": details or {}},
    )