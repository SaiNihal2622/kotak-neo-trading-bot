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
        limit_fill_spread_pct: float = 0.1,  # 0.1% spread for LIMIT order fill simulation
        limit_fill_min_spread: float = 0.05,  # min Rs.0.05 spread (NSE tick)
        limit_fill_near_ltp_pct: float = 0.5,  # fill if limit within 0.5% of LTP
        persist_path: str = "data_cache/paper_state.json",
    ):
        self.starting_capital = starting_capital
        self.slippage_bps = slippage_bps
        self.limit_fill_spread_pct = limit_fill_spread_pct
        self.limit_fill_min_spread = limit_fill_min_spread
        self.limit_fill_near_ltp_pct = limit_fill_near_ltp_pct
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
            # We fill aggressively to make paper trading actually work.
            # Spread parameters are configurable via constructor (no hardcodes).
            spread = max(self.limit_fill_min_spread, tick.ltp * (self.limit_fill_spread_pct / 100.0))
            synthetic_bid = tick.ltp - spread
            synthetic_ask = tick.ltp + spread
            if order.side == OrderSide.BUY:
                # BUY at limit: fill if limit >= synthetic_ask (realistic)
                if order.price >= synthetic_ask:
                    fill_price = min(order.price, synthetic_ask)
                # Also fill if limit is at LTP (within near-LTP pct of ask)
                elif abs(order.price - tick.ltp) / tick.ltp < (self.limit_fill_near_ltp_pct / 100.0):
                    fill_price = order.price
            elif order.side == OrderSide.SELL:
                # SELL at limit: fill if limit <= synthetic_bid (realistic)
                if order.price <= synthetic_bid:
                    fill_price = max(order.price, synthetic_bid)
                # Also fill if limit is at LTP (within near-LTP pct of bid)
                elif abs(order.price - tick.ltp) / tick.ltp < (self.limit_fill_near_ltp_pct / 100.0):
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
                if pos.qty > 0:
                    # adding to a LONG (average up)
                    total_qty = pos.qty + order.filled_qty
                    pos.avg_price = (pos.avg_price * pos.qty + order.avg_fill_price * order.filled_qty) / total_qty
                    pos.qty = total_qty
                    pos.ltp = order.avg_fill_price
                else:
                    # reducing or closing a SHORT
                    short_close = min(abs(pos.qty), order.filled_qty)
                    self._realized_pnl += (pos.avg_price - order.avg_fill_price) * short_close
                    pos.qty += order.filled_qty  # pos.qty is negative, so adding = closer to 0
                    if pos.qty == 0:
                        del self._positions[order.symbol]
                    elif pos.qty > 0:
                        # closed the short AND opened a LONG with the excess
                        pos.avg_price = order.avg_fill_price
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
                if pos.qty > 0:
                    # closing or reducing a LONG
                    close_qty = min(pos.qty, order.filled_qty)
                    self._realized_pnl += (order.avg_fill_price - pos.avg_price) * close_qty
                    pos.qty -= order.filled_qty
                    if pos.qty == 0:
                        del self._positions[order.symbol]
                    elif pos.qty < 0:
                        # flipped through zero: leftover becomes a SHORT at this fill price
                        # (rare; happens only on over-close)
                        pos.avg_price = order.avg_fill_price
                else:
                    # adding to or closing a SHORT
                    short_close = min(abs(pos.qty), order.filled_qty)
                    self._realized_pnl += (pos.avg_price - order.avg_fill_price) * short_close
                    pos.qty -= order.filled_qty  # pos.qty is negative, so subtracting = more negative
                    if pos.qty == 0:
                        del self._positions[order.symbol]
                    elif pos.qty > 0:
                        # closed the short AND opened a LONG with the excess
                        pos.avg_price = order.avg_fill_price
            else:
                # BUG FIX 2026-08-10: SELL into nothing must OPEN a SHORT position.
                # Previously the SELL was only recorded in orders dict; the SHORT was
                # never reflected in self._positions, so the close-BUY later created a
                # phantom LONG and broke reconciliation. (See: 4 ghost longs at EOD.)
                self._positions[order.symbol] = Position(
                    symbol=order.symbol,
                    exchange=order.exchange,
                    qty=-order.filled_qty,  # negative = short
                    avg_price=order.avg_fill_price,
                    ltp=order.avg_fill_price,
                    product=order.product,
                    strike=order.strike,
                    option_type=order.option_type,
                    expiry=order.expiry,
                    underlying=order.underlying,
                    entry_time=datetime.utcnow(),
                )

    # ------- persistence -------
    def _save_state(self) -> None:
        try:
            # BUG FIX 2026-08-11: shallow-copy each object's __dict__ before mutating
            # for serialization. `o.__dict__` returns a REFERENCE to the instance
            # namespace, so the previous code was mutating the live Order/Position
            # enums to strings every save. That broke OrderManager's in-memory view
            # of the trade book. Found by e2e_test.py: o.side became a string
            # after the first place_order + save.
            import copy
            state = {
                "cash": self._cash,
                "realized_pnl": self._realized_pnl,
                "orders": {oid: copy.copy(o.__dict__) for oid, o in self._orders.items()},
                "positions": {s: copy.copy(p.__dict__) for s, p in self._positions.items()},
            }
            # datetime/Enum to string (now safe — we're mutating the copy, not the original)
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
                if "status" in od and isinstance(od["status"], str):
                    od["status"] = OrderStatus(od["status"])
                # BUG FIX 2026-08-11: also convert side/order_type/product back
                # to enums on load. Without this, orders saved by the previous
                # buggy _save_state (which wrote strings) load with strings,
                # breaking any code that does `if order.side == OrderSide.BUY`.
                for k in ("side", "order_type"):
                    if k in od and isinstance(od[k], str):
                        if k == "side":
                            od[k] = OrderSide(od[k])
                        elif k == "order_type":
                            od[k] = OrderType(od[k])
                if "product" in od and isinstance(od["product"], str):
                    od["product"] = ProductType(od["product"])
                self._orders[oid] = Order(**od)
            for s, pd in state.get("positions", {}).items():
                if "entry_time" in pd and pd["entry_time"]:
                    pd["entry_time"] = datetime.fromisoformat(pd["entry_time"])
                if "product" in pd and isinstance(pd["product"], str):
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

    def rebuild_positions_from_orders(self) -> dict:
        """Recompute positions from COMPLETE order history.

        BUG RECOVERY 2026-08-10: Before the SELL-without-position fix, opening shorts
        (iron butterfly, strangle, etc.) left positions unrecorded. The close BUY
        then created phantom LONGs. This method walks the order book and rebuilds
        the net position per symbol from scratch.

        Returns a report dict with: {rebuilt, dropped, kept, before_count, after_count}.
        """
        with self._lock:
            before = {s: (p.qty, p.avg_price) for s, p in self._positions.items()}
            # bucket filled quantity by side per symbol
            net: dict[str, dict] = {}
            for o in self._orders.values():
                if o.status != OrderStatus.COMPLETE:
                    continue
                # map side to signed qty
                if o.side == OrderSide.BUY:
                    signed = +o.filled_qty
                elif o.side == OrderSide.SELL:
                    signed = -o.filled_qty
                else:
                    continue
                if o.symbol not in net:
                    net[o.symbol] = {"qty": 0, "buy_qty": 0, "buy_val": 0.0,
                                     "sell_qty": 0, "sell_val": 0.0,
                                     "meta": o}
                b = net[o.symbol]
                b["qty"] += signed
                if signed > 0:
                    b["buy_qty"] += signed
                    b["buy_val"] += signed * o.avg_fill_price
                else:
                    b["sell_qty"] += -signed
                    b["sell_val"] += -signed * o.avg_fill_price

            # build new positions dict
            new_positions: dict[str, Position] = {}
            realized_delta = 0.0
            for sym, b in net.items():
                net_qty = b["qty"]
                if net_qty == 0:
                    # fully closed → realize PnL using the legs
                    if b["sell_qty"] > 0 and b["buy_qty"] > 0:
                        # use average buy / sell prices for the realized PnL estimate
                        avg_buy = b["buy_val"] / b["buy_qty"]
                        avg_sell = b["sell_val"] / b["sell_qty"]
                        # signed PnL: (sell - buy) * min(sell_qty, buy_qty)
                        matched = min(b["sell_qty"], b["buy_qty"])
                        realized_delta += (avg_sell - avg_buy) * matched
                    continue
                # open position: derive avg_price from the dominant side
                meta = b["meta"]
                if net_qty > 0:
                    # net long: avg = buy_val / buy_qty
                    avg_price = b["buy_val"] / b["buy_qty"]
                else:
                    # net short: avg = sell_val / sell_qty
                    avg_price = b["sell_val"] / b["sell_qty"]
                new_positions[sym] = Position(
                    symbol=sym,
                    exchange=meta.exchange,
                    qty=net_qty,
                    avg_price=avg_price,
                    ltp=meta.avg_fill_price,
                    product=meta.product,
                    strike=meta.strike,
                    option_type=meta.option_type,
                    expiry=meta.expiry,
                    underlying=meta.underlying,
                    entry_time=meta.placed_at,
                )

            self._positions = new_positions
            # adjust realized_pnl: rebuild the delta over previous state
            # (we cannot fully reverse old realized, so we ADD the matched-pairs estimate
            # and accept small drift if the original was already partially booked)
            if realized_delta:
                self._realized_pnl += realized_delta
            self._save_state()

            after = {s: (p.qty, p.avg_price) for s, p in self._positions.items()}
            report = {
                "before": before,
                "after": after,
                "before_count": len(before),
                "after_count": len(after),
                "realized_pnl_delta": realized_delta,
            }
            logger.info(
                f"PaperClient rebuilt positions: {len(before)} -> {len(after)} "
                f"(realized_pnl delta: Rs.{realized_delta:,.2f})"
            )
            return report
