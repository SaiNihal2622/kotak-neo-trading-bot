"""Paper trading client.

Synthesizes fills from the live WebSocket LTP. Does NOT call the real broker.
All orders are intercepted, logged, and filled against a synthetic book.
This is the safe default for paper trading when the Kotak UAT is not yet provisioned.
"""
from __future__ import annotations

import json
import time
import uuid
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Callable, Optional

from loguru import logger

from .base import (
    BrokerClient,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    ProductType,
    Tick,
)


class PaperClient(BrokerClient):
    """In-process paper trading simulator.

    - Tracks a virtual book of orders and positions
    - Fills market orders at the most recent tick LTP (with simulated slippage)
    - Fills limit orders when the tick crosses the price
    - Persists state to a JSON file for crash recovery
    """

    def __init__(
        self,
        starting_capital: float = 300_000.0,
        slippage_bps: float = 5.0,  # 5 bps = 0.05% slippage on market orders
        persist_path: str = "data_cache/paper_state.json",
    ):
        self.starting_capital = starting_capital
        self.slippage_bps = slippage_bps
        self.persist_path = Path(persist_path)
        self.persist_path.parent.mkdir(parents=True, exist_ok=True)

        self._lock = RLock()
        self._orders: dict[str, Order] = {}
        self._positions: dict[str, Position] = {}
        self._ticks: dict[str, Tick] = {}
        self._tick_callbacks: list[Callable[[Tick], None]] = []
        self._cash = starting_capital
        self._realized_pnl = 0.0
        self._connected = False

        # load state if exists
        self._load_state()

    # ------- connection (no-op) -------
    def connect(self) -> None:
        with self._lock:
            self._connected = True
            logger.info(f"PaperClient connected | capital=₹{self._cash:,.0f} | "
                        f"orders={len(self._orders)} | positions={len(self._positions)}")

    def disconnect(self) -> None:
        with self._lock:
            self._connected = False
            self._save_state()
            logger.info("PaperClient disconnected")

    def is_connected(self) -> bool:
        return self._connected

    # ------- order management -------
    def place_order(self, order: Order, bracket=None, cover_sl: float = None) -> Order:
        """Place an order. bracket/cover_sl are accepted for API parity with NeoClient
        but ignored in paper mode (no server-side SL/target simulation)."""
        with self._lock:
            if not self._connected:
                raise RuntimeError("PaperClient not connected — call connect() first")
            order.order_id = f"PAPER-{uuid.uuid4().hex[:10].upper()}"
            order.placed_at = datetime.utcnow()
            order.status = OrderStatus.OPEN
            self._orders[order.order_id] = order
            tag = order.tag or ""
            if bracket:
                tag += f" [BRACKET sl={bracket.stop_loss} tgt={bracket.target} trail={bracket.trailing_sl_points}]"
            if cover_sl:
                tag += f" [COVER sl={cover_sl}]"
            logger.info(
                f"[PAPER] PLACE {order.order_id} {order.side.value} {order.qty}×{order.symbol} "
                f"{order.order_type.value} @ {order.price} ({tag})"
            )
            # attempt immediate fill
            self._try_fill(order)
            self._save_state()
            return order

    def modify_order(self, order_id: str, **kwargs) -> Order:
        with self._lock:
            order = self._orders.get(order_id)
            if not order:
                raise KeyError(f"Order {order_id} not found")
            if order.status in (OrderStatus.COMPLETE, OrderStatus.CANCELLED, OrderStatus.REJECTED):
                raise ValueError(f"Cannot modify {order.status.value} order")
            for k, v in kwargs.items():
                if hasattr(order, k):
                    setattr(order, k, v)
            logger.info(f"[PAPER] MODIFY {order_id} {kwargs}")
            self._try_fill(order)
            self._save_state()
            return order

    def cancel_order(self, order_id: str) -> Order:
        with self._lock:
            order = self._orders.get(order_id)
            if not order:
                raise KeyError(f"Order {order_id} not found")
            if order.status == OrderStatus.COMPLETE:
                raise ValueError("Cannot cancel filled order")
            order.status = OrderStatus.CANCELLED
            logger.info(f"[PAPER] CANCEL {order_id}")
            self._save_state()
            return order

    def get_order(self, order_id: str) -> Order:
        with self._lock:
            return self._orders.get(order_id)  # type: ignore[return-value]

    def get_positions(self) -> list[Position]:
        with self._lock:
            # mark-to-market all positions
            for pos in self._positions.values():
                tick = self._ticks.get(pos.symbol)
                if tick:
                    pos.ltp = tick.ltp
                    pos.pnl = (pos.ltp - pos.avg_price) * pos.qty
            return list(self._positions.values())

    def get_holdings(self) -> list[Position]:
        return []  # paper has no delivery holdings

    def get_margins(self) -> dict:
        with self._lock:
            used = sum(abs(p.qty) * p.ltp for p in self._positions.values())
            return {
                "available": self._cash - used,
                "used": used,
                "total": self._cash,
                "realized_pnl": self._realized_pnl,
                "unrealized_pnl": sum(p.pnl for p in self._positions.values()),
            }

    def get_ltp(self, symbol: str, exchange: str = "NFO") -> float:
        with self._lock:
            tick = self._ticks.get(symbol)
            return tick.ltp if tick else 0.0

    def subscribe(self, symbols: list[str], exchange: str = "NFO") -> None:
        logger.info(f"[PAPER] subscribe {len(symbols)} symbols")

    def on_tick(self, callback: Callable[[Tick], None]) -> None:
        self._tick_callbacks.append(callback)

    # ------- market data injection (used by data/live_feed) -------
    def inject_tick(self, tick: Tick) -> None:
        """Feed a real tick into the paper book. Public for the live feed."""
        with self._lock:
            self._ticks[tick.symbol] = tick
            # mark-to-market
            pos = self._positions.get(tick.symbol)
            if pos:
                pos.ltp = tick.ltp
                pos.pnl = (pos.ltp - pos.avg_price) * pos.qty
            # check open orders
            for order in self._orders.values():
                if order.status == OrderStatus.OPEN and order.symbol == tick.symbol:
                    self._try_fill(order)
            self._save_state()
        for cb in self._tick_callbacks:
            try:
                cb(tick)
            except Exception as e:
                logger.exception(f"tick callback error: {e}")

    # ------- internals -------
    def _try_fill(self, order: Order) -> None:
        tick = self._ticks.get(order.symbol)
        if not tick:
            return  # no price yet, leave open
        order.expected_fill_price = tick.ltp
        fill_price = 0.0
        if order.order_type == OrderType.MARKET:
            # simulated slippage in direction of trade
            slip = tick.ltp * (self.slippage_bps / 10_000)
            fill_price = tick.ltp + (slip if order.side == OrderSide.BUY else -slip)
        elif order.order_type == OrderType.LIMIT:
            # FIX 2026-08-07: For paper trading, fill LIMIT orders with realistic probability
            # In a real market, a SELL at the LTP would have a buyer within 1-2 ticks
            # We fill aggressively to make paper trading actually work
            spread = max(0.05, tick.ltp * 0.001)  # assume 0.1% spread or min Rs.0.05
            synthetic_bid = tick.ltp - spread
            synthetic_ask = tick.ltp + spread
            if order.side == OrderSide.BUY:
                # BUY at limit: fill if limit >= synthetic_ask (realistic)
                if order.price >= synthetic_ask:
                    fill_price = min(order.price, synthetic_ask)
                # Also fill if limit is at LTP (within 0.5% of ask)
                elif abs(order.price - tick.ltp) / tick.ltp < 0.005:
                    fill_price = order.price
            elif order.side == OrderSide.SELL:
                # SELL at limit: fill if limit <= synthetic_bid (realistic)
                if order.price <= synthetic_bid:
                    fill_price = max(order.price, synthetic_bid)
                # Also fill if limit is at LTP (within 0.5% of bid)
                elif abs(order.price - tick.ltp) / tick.ltp < 0.005:
                    fill_price = order.price
        elif order.order_type == OrderType.SL:
            if (order.side == OrderSide.BUY and tick.ltp >= order.trigger_price) or \
               (order.side == OrderSide.SELL and tick.ltp <= order.trigger_price):
                fill_price = order.price if order.price > 0 else tick.ltp
        elif order.order_type == OrderType.SL_M:
            if (order.side == OrderSide.BUY and tick.ltp >= order.trigger_price) or \
               (order.side == OrderSide.SELL and tick.ltp <= order.trigger_price):
                fill_price = tick.ltp
        if fill_price > 0:
            order.avg_fill_price = round(fill_price, 2)
            order.filled_qty = order.qty
            order.status = OrderStatus.COMPLETE
            order.filled_at = datetime.utcnow()
            self._apply_fill(order)
            logger.info(
                f"[PAPER] FILL {order.order_id} {order.qty}×{order.symbol} @ {order.avg_fill_price} "
                f"(tick={tick.ltp})"
            )

    def _apply_fill(self, order: Order) -> None:
        pos = self._positions.get(order.symbol)
        fill_value = order.filled_qty * order.avg_fill_price
        if order.side == OrderSide.BUY:
            self._cash -= fill_value
            if pos:
                # average up
                total_qty = pos.qty + order.filled_qty
                pos.avg_price = (pos.avg_price * pos.qty + order.avg_fill_price * order.filled_qty) / total_qty
                pos.qty = total_qty
                pos.ltp = order.avg_fill_price
            else:
                self._positions[order.symbol] = Position(
                    symbol=order.symbol,
                    exchange=order.exchange,
                    qty=order.filled_qty,
                    avg_price=order.avg_fill_price,
                    ltp=order.avg_fill_price,
                    product=order.product,
                    strike=order.strike,
                    option_type=order.option_type,
                    expiry=order.expiry,
                    underlying=order.underlying,
                    entry_time=datetime.utcnow(),
                )
        else:  # SELL
            self._cash += fill_value
            if pos:
                # realize P&L
                if pos.qty > 0:
                    self._realized_pnl += (order.avg_fill_price - pos.avg_price) * order.filled_qty
                else:
                    self._realized_pnl += (pos.avg_price - order.avg_fill_price) * order.filled_qty
                pos.qty -= order.filled_qty
                if pos.qty == 0:
                    del self._positions[order.symbol]

    # ------- persistence -------
    def _save_state(self) -> None:
        try:
            state = {
                "cash": self._cash,
                "realized_pnl": self._realized_pnl,
                "orders": {oid: o.__dict__ for oid, o in self._orders.items()},
                "positions": {s: p.__dict__ for s, p in self._positions.items()},
            }
            # datetime/Enum to string
            for oid, od in state["orders"].items():
                for k, v in list(od.items()):
                    if isinstance(v, datetime):
                        od[k] = v.isoformat()
                    elif isinstance(v, OrderStatus):
                        od[k] = v.value
                    elif isinstance(v, (OrderSide, OrderType, ProductType)):
                        od[k] = v.value
            for s, pd in state["positions"].items():
                for k, v in list(pd.items()):
                    if isinstance(v, datetime):
                        pd[k] = v.isoformat()
                    elif isinstance(v, ProductType):
                        pd[k] = v.value
            # write atomically: tmp file then replace, with retry on WinError 5
            tmp = self.persist_path.with_suffix(".tmp")
            json_text = json.dumps(state, indent=2, default=str, ensure_ascii=False)
            for attempt in range(3):
                try:
                    tmp.write_text(json_text, encoding="utf-8")
                    # try replace, may fail if file is locked by another reader
                    if self.persist_path.exists():
                        # on Windows, os.replace works even if file is open for reading
                        import os
                        os.replace(tmp, self.persist_path)
                    else:
                        tmp.replace(self.persist_path)
                    return
                except (PermissionError, OSError) as e:
                    if attempt < 2:
                        import time as _t
                        _t.sleep(0.05 * (attempt + 1))
                    else:
                        # last attempt failed — fall back to direct write
                        try:
                            self.persist_path.write_text(json_text, encoding="utf-8")
                            return
                        except Exception as ee:
                            raise
        except Exception as e:
            logger.warning(f"PaperClient state save failed: {e}")

    def _load_state(self) -> None:
        if not self.persist_path.exists():
            return
        try:
            state = json.loads(self.persist_path.read_text(encoding="utf-8"))
            self._cash = state.get("cash", self.starting_capital)
            self._realized_pnl = state.get("realized_pnl", 0.0)
            for oid, od in state.get("orders", {}).items():
                if "placed_at" in od and od["placed_at"]:
                    od["placed_at"] = datetime.fromisoformat(od["placed_at"])
                if "filled_at" in od and od["filled_at"]:
                    od["filled_at"] = datetime.fromisoformat(od["filled_at"])
                if "status" in od:
                    od["status"] = OrderStatus(od["status"])
                self._orders[oid] = Order(**od)
            for s, pd in state.get("positions", {}).items():
                if "entry_time" in pd and pd["entry_time"]:
                    pd["entry_time"] = datetime.fromisoformat(pd["entry_time"])
                if "product" in pd:
                    pd["product"] = ProductType(pd["product"])
                self._positions[s] = Position(**pd)
            logger.info(f"PaperClient loaded state: {len(self._orders)} orders, {len(self._positions)} positions")
        except Exception as e:
            logger.warning(f"PaperClient state load failed: {e}")

    def reset(self) -> None:
        """Wipe paper state and start fresh."""
        with self._lock:
            self._orders.clear()
            self._positions.clear()
            self._ticks.clear()
            self._cash = self.starting_capital
            self._realized_pnl = 0.0
            if self.persist_path.exists():
                self.persist_path.unlink()
            logger.info("PaperClient reset")
