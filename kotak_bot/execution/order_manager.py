"""Order manager.

Turns a TradePlan (multi-leg) into a sequence of broker orders, handles partial fills,
and tracks the resulting positions. Includes a simple smart router (limit vs market).

Now supports:
- Bracket orders (server-side SL + target + trailing) for directional trades
- Cover orders (server-side mandatory SL) for single-leg entries
- Regular orders for multi-leg defined-risk strategies (iron condor, strangle)
- Pre-trade margin check (margin_required) for every order
- Persisted state (JSON) so bot restarts don't lose _trades
"""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Callable, Optional

from loguru import logger

from kotak_bot.broker.base import (
    BrokerClient,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    ProductType,
)
from kotak_bot.broker.neo_client import BracketOrderSpec
from kotak_bot.strategy.base import TradePlan, StrategyName


@dataclass
class ManagedTrade:
    trade_id: str = ""
    plan: TradePlan = None
    orders: list[Order] = field(default_factory=list)
    opened_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    realized_pnl: float = 0.0
    target_hit: bool = False
    stop_hit: bool = False
    exit_reason: str = ""
    # Derived top-level fields for fast queries without traversing orders.
    # Populated by _save_state / _load_state and by execute_plan / close_trade.
    status: str = "open"  # "open" | "closed"
    underlying: str = ""  # mirrored from plan.underlying for fast filtering
    leg_count: int = 0     # len(orders) at open time
    pnl: float = 0.0       # current unrealized + realized, for ranking/queries
    entry_time: Optional[datetime] = None  # alias for opened_at for clarity


class OrderManager:
    """Translates TradePlans into broker orders, tracks the resulting positions.

    PERSISTENCE: when `persist_path` is set, the entire _trades dict (including
    open and closed trades) is written to JSON after every open/close event and
    reloaded on construction. This survives bot restarts — without it, every
    restart loses the in-memory trade book and the EOD square-off only sees
    whatever trades the new process happens to discover.
    """

    def __init__(self, broker: BrokerClient, smart_router: bool = True,
                 persist_path: str = "data_cache/trades_state.json",
                 resilient_executor: Optional[Any] = None):
        self.broker = broker
        self.smart_router = smart_router
        # Optional Phase 1.3 resilient executor — if set, place_order is routed
        # through it for retry/backoff + cancel-replace + fallback data
        self._resilient = resilient_executor
        self._trades: dict[str, ManagedTrade] = {}
        self._symbol_to_trade: dict[str, str] = {}
        self._on_trade_event: Optional[Callable] = None
        self._lock = RLock()
        self.persist_path = Path(persist_path)
        self.persist_path.parent.mkdir(parents=True, exist_ok=True)
        self._load_state()

    def set_resilient_executor(self, resilient) -> None:
        """Inject the resilient executor after construction (used by __main__)."""
        self._resilient = resilient

    def set_event_callback(self, cb: Callable) -> None:
        self._on_trade_event = cb

    def _save_state(self) -> None:
        """Persist the entire _trades dict to JSON. Atomic write + retry."""
        with self._lock:
            try:
                # First, refresh derived fields on each trade so what we save
                # is always in sync with the orders.
                for t in self._trades.values():
                    self._refresh_derived(t)
                state = {
                    "trades": {
                        tid: {
                            "trade_id": t.trade_id,
                            "plan": self._plan_to_dict(t.plan) if t.plan else None,
                            "orders": [self._order_to_dict(o) for o in t.orders],
                            "opened_at": t.opened_at.isoformat() if t.opened_at else None,
                            "closed_at": t.closed_at.isoformat() if t.closed_at else None,
                            "realized_pnl": t.realized_pnl,
                            "target_hit": t.target_hit,
                            "stop_hit": t.stop_hit,
                            "exit_reason": t.exit_reason,
                            # Derived top-level fields (consumed by reconcile + dashboard)
                            "status": t.status,
                            "underlying": t.underlying,
                            "leg_count": t.leg_count,
                            "pnl": t.pnl,
                            "entry_time": t.entry_time.isoformat() if t.entry_time else None,
                        }
                        for tid, t in self._trades.items()
                    },
                    "symbol_to_trade": dict(self._symbol_to_trade),
                }
                tmp = self.persist_path.with_suffix(".tmp")
                tmp.write_text(
                    json.dumps(state, indent=2, default=str, ensure_ascii=False),
                    encoding="utf-8",
                )
                os.replace(tmp, self.persist_path)
            except Exception as e:
                logger.warning(f"OrderManager state save failed: {e}")

    @staticmethod
    def _refresh_derived(t: "ManagedTrade") -> None:
        """Recompute derived top-level fields on a trade from its current orders + plan."""
        # Status: 'closed' if closed_at is set, else 'open'
        t.status = "closed" if t.closed_at is not None else "open"
        # Underlying: mirror from plan
        t.underlying = (t.plan.underlying if t.plan and getattr(t.plan, "underlying", None) else "")
        # Leg count
        t.leg_count = len(t.orders)
        # Entry time = opened_at
        t.entry_time = t.opened_at
        # P&L: realized + (unrealized if open)
        t.pnl = float(t.realized_pnl or 0.0)

    def _load_state(self) -> None:
        if not self.persist_path.exists():
            return
        try:
            state = json.loads(self.persist_path.read_text(encoding="utf-8"))
            from kotak_bot.strategy.base import TradePlan, StrategyName
            for tid, td in state.get("trades", {}).items():
                plan = None
                if td.get("plan"):
                    p = td["plan"]
                    plan = TradePlan(
                        strategy=StrategyName(p["strategy"]),
                        underlying=p.get("underlying", ""),
                        legs=p.get("legs", []),
                        target=p.get("target", 0.0),
                        stop=p.get("stop", 0.0),
                        confidence=p.get("confidence", 0.0),
                        reason=p.get("reason", ""),
                        expiry=p.get("expiry", ""),
                        expected_hold_minutes=p.get("expected_hold_minutes", 60),
                    )
                orders = [self._dict_to_order(od) for od in td.get("orders", [])]
                opened_at = datetime.fromisoformat(td["opened_at"]) if td.get("opened_at") else None
                closed_at = datetime.fromisoformat(td["closed_at"]) if td.get("closed_at") else None
                trade = ManagedTrade(
                    trade_id=td.get("trade_id", tid),
                    plan=plan,
                    orders=orders,
                    opened_at=opened_at,
                    closed_at=closed_at,
                    realized_pnl=td.get("realized_pnl", 0.0),
                    target_hit=td.get("target_hit", False),
                    stop_hit=td.get("stop_hit", False),
                    exit_reason=td.get("exit_reason", ""),
                    # Derived top-level fields — fall back to old-schema derivations
                    status=td.get("status") or ("closed" if closed_at is not None else "open"),
                    underlying=td.get("underlying") or (plan.underlying if plan else ""),
                    leg_count=td.get("leg_count", len(orders)),
                    pnl=td.get("pnl", td.get("realized_pnl", 0.0)),
                    entry_time=(
                        datetime.fromisoformat(td["entry_time"])
                        if td.get("entry_time")
                        else opened_at
                    ),
                )
                self._trades[tid] = trade
            self._symbol_to_trade = state.get("symbol_to_trade", {})
            logger.info(
                f"OrderManager loaded state: {len(self._trades)} trades "
                f"({len([t for t in self._trades.values() if t.closed_at is None])} open)"
            )
        except Exception as e:
            logger.warning(f"OrderManager state load failed: {e}")

    @staticmethod
    def _plan_to_dict(plan) -> dict:
        if not plan:
            return {}
        return {
            "strategy": plan.strategy.value,
            "underlying": plan.underlying,
            "legs": list(plan.legs),
            "target": plan.target,
            "stop": plan.stop,
            "confidence": plan.confidence,
            "reason": plan.reason,
            "expiry": plan.expiry,
            "expected_hold_minutes": plan.expected_hold_minutes,
        }

    @staticmethod
    def _order_to_dict(o: Order) -> dict:
        d = o.__dict__.copy()
        for k, v in list(d.items()):
            if isinstance(v, datetime):
                d[k] = v.isoformat()
            elif hasattr(v, "value"):  # Enum
                d[k] = v.value
        return d

    @staticmethod
    def _dict_to_order(d: dict) -> Order:
        # Convert string side/order_type back to Enum
        for k in ("side", "order_type", "product"):
            if k in d and isinstance(d[k], str):
                if k == "side":
                    d[k] = OrderSide(d[k])
                elif k == "order_type":
                    d[k] = OrderType(d[k])
                elif k == "product":
                    d[k] = ProductType(d[k])
        if d.get("placed_at") and isinstance(d["placed_at"], str):
            d["placed_at"] = datetime.fromisoformat(d["placed_at"])
        if d.get("filled_at") and isinstance(d["filled_at"], str):
            d["filled_at"] = datetime.fromisoformat(d["filled_at"])
        if d.get("status") and isinstance(d["status"], str):
            d["status"] = OrderStatus(d["status"])
        return Order(**d)

    def execute_plan(self, plan: TradePlan, qty: int, expiry: str = "", lot_sizes: dict | None = None,
                     use_bracket: bool = True,
                     bracket_config: dict | None = None) -> ManagedTrade:
        """Place all legs of a plan.

        - For 1-leg directional trades: use BRACKET order (server-side SL+target+trailing)
        - For multi-leg defined-risk (iron condor, strangle): use regular LIMIT orders
        - For cover orders: not used in this version (multi-leg only)
        bracket_config: dict with keys {sl_pct, target_mult, trail_pct} for bracket order
                        calculation. If None, uses defaults from settings (no hardcodes).
        """
        # Bracket defaults — pulled from settings if available, else these are the last-resort defaults.
        # Note: __main__.py should pass cfg.risk.bracket.* values, but we have safe defaults
        # for unit tests and other call sites.
        bc = {
            "sl_pct": 0.5,        # SL = entry * sl_pct (50% of premium for long options)
            "target_mult": 1.5,   # target = entry * target_mult (50% above entry)
            "trail_pct": 0.1,     # trailing SL trail = entry * trail_pct
            **(bracket_config or {}),
        }

        lot_sizes = lot_sizes or {}
        lot_size = lot_sizes.get(plan.underlying, 1)
        trade_id = f"T-{uuid.uuid4().hex[:10].upper()}"
        trade = ManagedTrade(trade_id=trade_id, plan=plan, opened_at=datetime.utcnow())
        is_single_leg = len(plan.legs) == 1
        # If single-leg directional and bracket enabled, use bracket
        use_bracket_for_this = use_bracket and is_single_leg and plan.strategy == StrategyName.DIRECTIONAL_DEBIT
        for leg in plan.legs:
            strike = leg.get("strike", 0)
            opt_type = leg.get("opt_type", "")
            symbol = self._format_symbol(plan.underlying, expiry, strike, opt_type)
            order = Order(
                symbol=symbol,
                side=OrderSide(leg["side"]),
                qty=leg.get("qty", 1) * qty * lot_size,
                order_type=OrderType(leg.get("order_type", "LIMIT")),
                product=ProductType.MIS,
                price=leg.get("price", 0),
                tag=leg.get("tag", trade_id),
                exchange="NFO",
                strike=strike,
                option_type=opt_type,
                expiry=expiry,
                underlying=plan.underlying,
            )
            # Pre-trade margin check (NeoClient only)
            bracket = None
            if use_bracket_for_this and leg["side"] == "BUY":
                # Build bracket using configurable parameters (no hardcodes)
                entry = leg.get("price", 0)
                if entry > 0:
                    sl = round(entry * bc["sl_pct"], 2)
                    target = round(entry * bc["target_mult"], 2)
                    trailing = round(entry * bc["trail_pct"], 2)
                    bracket = BracketOrderSpec(
                        entry_price=entry,
                        stop_loss=sl,
                        target=target,
                        trailing_sl=True,
                        trailing_sl_points=trailing,
                    )
                    logger.info(f"  -> Using BRACKET order: SL={sl} target={target} trail={trailing}")
            # Use bracket= for the BUY leg, None for hedging legs (multi-leg won't use bracket)
            # Route through ResilientExecutor if injected (Phase 1.3)
            if self._resilient is not None:
                placed = self._resilient.place_order(order, bracket=bracket)
            else:
                placed = self.broker.place_order(order, bracket=bracket)
            trade.orders.append(placed)
        self._trades[trade_id] = trade
        for o in trade.orders:
            if o.symbol not in self._symbol_to_trade:
                self._symbol_to_trade[o.symbol] = trade_id
        logger.info(f"Executed plan {trade_id}: {plan.strategy.value} {len(plan.legs)} legs" +
                    (" [BRACKET]" if use_bracket_for_this else ""))
        if self._on_trade_event:
            try:
                self._on_trade_event("opened", trade)
            except Exception as e:
                logger.exception(f"trade event cb: {e}")
        self._save_state()
        return trade

    def close_trade(self, trade_id: str, reason: str = "manual") -> ManagedTrade:
        trade = self._trades.get(trade_id)
        if not trade:
            raise KeyError(trade_id)
        realized_pnl_total = 0.0
        pending_closes = 0
        for order in trade.orders:
            # Only place close orders for ENTRY legs. We detect entry legs by tag:
            # close_* orders are placed by us in the same loop, so we skip them on
            # the second pass. To keep the loop safe in either ordering, we match
            # by checking that the order's tag does NOT start with 'close_'.
            if order.status != OrderStatus.COMPLETE:
                continue
            if order.tag and order.tag.startswith("close_"):
                # already a close order (defensive — shouldn't happen in normal flow)
                continue
            close_side = OrderSide.SELL if order.side == OrderSide.BUY else OrderSide.BUY
            close_order = Order(
                symbol=order.symbol,
                side=close_side,
                qty=order.filled_qty,
                order_type=OrderType.MARKET,
                product=order.product,
                tag=f"close_{order.order_id}",
                exchange=order.exchange,
                strike=order.strike,
                option_type=order.option_type,
                expiry=order.expiry,
                underlying=order.underlying,
            )
            if self._resilient is not None:
                placed = self._resilient.place_order(close_order)
            else:
                placed = self.broker.place_order(close_order)
            trade.orders.append(placed)

            # P&L attribution: compute per-leg realized P&L if the close filled.
            # In paper mode, market orders against cached ticks fill synchronously,
            # so avg_fill_price is set on return. In live mode this is async — the
            # leg is recorded as 0 here and will be backfilled on next settle pass.
            leg_pnl = self._leg_pnl(order, placed)
            if leg_pnl is not None:
                realized_pnl_total += leg_pnl
            else:
                pending_closes += 1
        for s, tid in list(self._symbol_to_trade.items()):
            if tid == trade_id:
                del self._symbol_to_trade[s]
        trade.closed_at = datetime.utcnow()
        trade.exit_reason = reason
        trade.realized_pnl = round(realized_pnl_total, 2)
        if pending_closes:
            logger.warning(
                f"[{trade_id}] {pending_closes} close order(s) not yet filled at close_trade time; "
                f"realized_pnl={trade.realized_pnl} is partial. Will be backfilled by settle."
            )
        if self._on_trade_event:
            try:
                self._on_trade_event("closed", trade)
            except Exception as e:
                logger.exception(f"trade event cb: {e}")
        self._save_state()
        return trade

    @staticmethod
    def _leg_pnl(entry_order: Order, close_order: Order) -> Optional[float]:
        """Compute realized P&L for a single (entry, close) order pair.

        Returns None if the close order is not yet filled (avg_fill_price == 0 or
        status != COMPLETE). Returns 0.0 if entry_order or close_order is malformed.
        For options: BUY leg P&L = (exit - entry) * qty; SELL leg = (entry - exit) * qty.
        """
        try:
            if entry_order.avg_fill_price <= 0:
                return 0.0
            if close_order.status != OrderStatus.COMPLETE or close_order.avg_fill_price <= 0:
                return None
            entry_px = entry_order.avg_fill_price
            exit_px = close_order.avg_fill_price
            qty = entry_order.filled_qty or close_order.filled_qty
            if entry_order.side == OrderSide.BUY:
                return round((exit_px - entry_px) * qty, 2)
            else:  # SELL (short)
                return round((entry_px - exit_px) * qty, 2)
        except Exception:
            return 0.0

    def backfill_realized_pnl(self) -> int:
        """Recompute realized_pnl for all closed trades from their order pairs.

        Returns the number of trades that were backfilled (changed from 0 / stale).
        Used to repair historical trades that closed before the attribution fix
        landed (e.g. the 4 closed-but-0.0 trades from the 2026-08-21 / 2026-08-24
        paper sessions).

        Algorithm: for each closed trade, pair entry orders (tag does NOT start
        with 'close_') with close orders (tag starts with 'close_') by symbol.
        Sum the per-leg P&L and overwrite trade.realized_pnl if it differs.
        """
        n_fixed = 0
        with self._lock:
            for tid, t in list(self._trades.items()):
                if t.closed_at is None:
                    continue
                # Build close-order lookup keyed by entry order_id encoded in tag
                # close_<entry_order_id> -> close order
                close_by_entry = {}
                for o in t.orders:
                    if o.tag and o.tag.startswith("close_"):
                        entry_oid = o.tag[len("close_"):]
                        close_by_entry[entry_oid] = o
                # Walk entry orders, find matching close, accumulate
                total = 0.0
                for entry in t.orders:
                    if entry.tag and entry.tag.startswith("close_"):
                        continue
                    if entry.status != OrderStatus.COMPLETE:
                        continue
                    close = close_by_entry.get(entry.order_id)
                    if close is None:
                        continue
                    leg = self._leg_pnl(entry, close)
                    if leg is not None:
                        total += leg
                total = round(total, 2)
                if abs(total - (t.realized_pnl or 0.0)) > 0.01:
                    logger.info(
                        f"[backfill] {tid} realized_pnl {t.realized_pnl} -> {total} "
                        f"({len([o for o in t.orders if not (o.tag or '').startswith('close_')])} legs)"
                    )
                    t.realized_pnl = total
                    n_fixed += 1
            if n_fixed > 0:
                self._save_state()
        return n_fixed

    def square_off_all(self, reason: str = "eod") -> int:
        closed = 0
        for tid in list(self._trades.keys()):
            trade = self._trades[tid]
            if trade.closed_at is None:
                self.close_trade(tid, reason=reason)
                closed += 1
        return closed

    def open_trades(self) -> list[ManagedTrade]:
        return [t for t in self._trades.values() if t.closed_at is None]

    def get_trade_by_symbol(self, symbol: str) -> Optional[ManagedTrade]:
        tid = self._symbol_to_trade.get(symbol)
        if not tid:
            return None
        return self._trades.get(tid)

    def _format_symbol(self, underlying: str, expiry: str, strike: float, opt_type: str) -> str:
        if not expiry:
            return f"{underlying}{int(strike)}{opt_type}"
        try:
            dt = datetime.strptime(expiry, "%Y-%m-%d")
            expiry_str = dt.strftime("%d%b%y").upper()
        except Exception:
            expiry_str = expiry
        return f"{underlying}{expiry_str}{int(strike)}{opt_type}"

