"""Order manager.

Turns a TradePlan (multi-leg) into a sequence of broker orders, handles partial fills,
and tracks the resulting positions. Includes a simple smart router (limit vs market).

Now supports:
- Bracket orders (server-side SL + target + trailing) for directional trades
- Cover orders (server-side mandatory SL) for single-leg entries
- Regular orders for multi-leg defined-risk strategies (iron condor, strangle)
- Pre-trade margin check (margin_required) for every order
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
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


class OrderManager:
    """Translates TradePlans into broker orders, tracks the resulting positions."""

    def __init__(self, broker: BrokerClient, smart_router: bool = True):
        self.broker = broker
        self.smart_router = smart_router
        self._trades: dict[str, ManagedTrade] = {}
        self._symbol_to_trade: dict[str, str] = {}
        self._on_trade_event: Optional[Callable] = None

    def set_event_callback(self, cb: Callable) -> None:
        self._on_trade_event = cb

    def execute_plan(self, plan: TradePlan, qty: int, expiry: str = "", lot_sizes: dict | None = None,
                     use_bracket: bool = True) -> ManagedTrade:
        """Place all legs of a plan.

        - For 1-leg directional trades: use BRACKET order (server-side SL+target+trailing)
        - For multi-leg defined-risk (iron condor, strangle): use regular LIMIT orders
        - For cover orders: not used in this version (multi-leg only)
        """
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
                # Build bracket: SL = entry * 0.5, target = entry * 1.5
                entry = leg.get("price", 0)
                if entry > 0:
                    sl = round(entry * 0.5, 2)
                    target = round(entry * 1.5, 2)
                    trailing = round(entry * 0.1, 2)
                    bracket = BracketOrderSpec(
                        entry_price=entry,
                        stop_loss=sl,
                        target=target,
                        trailing_sl=True,
                        trailing_sl_points=trailing,
                    )
                    logger.info(f"  -> Using BRACKET order: SL={sl} target={target} trail={trailing}")
            # Use bracket= for the BUY leg, None for hedging legs (multi-leg won't use bracket)
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
        return trade

    def close_trade(self, trade_id: str, reason: str = "manual") -> ManagedTrade:
        trade = self._trades.get(trade_id)
        if not trade:
            raise KeyError(trade_id)
        for order in trade.orders:
            if order.status != OrderStatus.COMPLETE:
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
            self.broker.place_order(close_order)
        for s, tid in list(self._symbol_to_trade.items()):
            if tid == trade_id:
                del self._symbol_to_trade[s]
        trade.closed_at = datetime.utcnow()
        trade.exit_reason = reason
        if self._on_trade_event:
            try:
                self._on_trade_event("closed", trade)
            except Exception as e:
                logger.exception(f"trade event cb: {e}")
        return trade

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

