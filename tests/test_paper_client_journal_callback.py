"""Tests for the inline trade_journal callback on PaperClient.

Verifies that:
  1. on_fill() registers a callback that fires after every fill
  2. The callback receives (order, realized_delta) with the correct delta
  3. For pure opens (no prior position), realized_delta == 0
  4. For closes that reduce a long, realized_delta = (fill - avg) * qty
  5. For closes that cover a short, realized_delta = (avg - fill) * qty
  6. Exceptions in callbacks don't break the fill flow
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from kotak_bot.broker.paper_client import PaperClient
from kotak_bot.broker.base import (
    Order, OrderSide, OrderType, ProductType, OrderStatus, Tick
)


def _make_order(symbol="NIFTY10SEP2624300PE", side=OrderSide.BUY, qty=75,
                price=0.0, ot=OrderType.MARKET, tag=""):
    return Order(
        order_id="",
        symbol=symbol,
        exchange="NFO",
        side=side,
        qty=qty,
        price=price,
        order_type=ot,
        product=ProductType.MIS,
        strike=24300,
        option_type="PE",
        expiry="2026-09-10",
        underlying="NIFTY",
        tag=tag,
    )


def test_on_fill_callback_fires_on_open(tmp_path):
    """A pure open should fire the callback with realized_delta == 0."""
    persist = tmp_path / "paper_state.json"
    pc = PaperClient(starting_capital=200000, fill_mode="market_like", persist_path=str(persist))
    pc.connect()

    fired = []
    pc.on_fill(lambda order, delta: fired.append((order.order_id, delta, order.symbol, order.side.value)))

    o = _make_order(side=OrderSide.BUY, qty=75, tag="QUANT-bear_put_v")
    placed = pc.place_order(o)
    assert placed.status == OrderStatus.COMPLETE
    assert len(fired) == 1
    oid, delta, sym, side = fired[0]
    assert oid == placed.order_id
    assert delta == 0.0  # pure open
    assert sym == "NIFTY10SEP2624300PE"
    assert side == "BUY"


def test_on_fill_callback_fires_on_close_with_correct_delta(tmp_path):
    """A close should fire the callback with the realized P&L delta."""
    persist = tmp_path / "paper_state.json"
    pc = PaperClient(starting_capital=200000, fill_mode="market_like", persist_path=str(persist))
    pc.connect()

    fired = []
    pc.on_fill(lambda order, delta: fired.append((order.symbol, order.side.value, delta, order.avg_fill_price)))

    # Open long
    buy_ord = pc.place_order(_make_order(side=OrderSide.BUY, qty=75, tag="QUANT-test"))
    open_px = buy_ord.avg_fill_price
    # Close long at 100.0 (slippage makes fill = ~99.95)
    sell_ord = pc.place_order(_make_order(side=OrderSide.SELL, qty=75, price=100.0, tag="CLOSE"))
    close_px = sell_ord.avg_fill_price

    assert len(fired) == 2
    # First call: open, delta = 0
    assert fired[0][0] == "NIFTY10SEP2624300PE"
    assert fired[0][1] == "BUY"
    assert fired[0][2] == 0.0
    # Second call: close
    sym, side, delta, actual_close_px = fired[1]
    assert sym == "NIFTY10SEP2624300PE"
    assert side == "SELL"
    # delta = (close_px - open_px) * 75 for a SELL closing a LONG
    expected = (close_px - open_px) * 75
    assert delta == pytest.approx(expected, abs=0.5)


def test_on_fill_callback_short_cover(tmp_path):
    """A short cover should compute positive delta when closing below the open price."""
    persist = tmp_path / "paper_state.json"
    pc = PaperClient(starting_capital=200000, fill_mode="market_like", persist_path=str(persist))
    pc.connect()

    fired = []
    pc.on_fill(lambda order, delta: fired.append((order.symbol, order.side.value, delta, order.avg_fill_price)))

    # Open short by SELLing first (slippage makes fill = 199.90, not 200)
    sell_ord = pc.place_order(_make_order(side=OrderSide.SELL, qty=75, price=200.0, tag="QUANT-short"))
    sell_fill_px = sell_ord.avg_fill_price
    # Cover short by BUYing at 100 (slippage makes fill = 100.05)
    pc.place_order(_make_order(side=OrderSide.BUY, qty=75, price=100.0, tag="CLOSE"))

    assert len(fired) == 2
    # Second call: BUY covering SHORT, delta = (open_px - close_px) * 75
    sym, side, delta, close_px = fired[1]
    assert sym == "NIFTY10SEP2624300PE"
    assert side == "BUY"
    expected = (sell_fill_px - close_px) * 75
    assert delta == pytest.approx(expected, abs=0.5)


def test_on_fill_callback_exception_doesnt_break_fill(tmp_path):
    """A callback that raises should not break the fill flow."""
    persist = tmp_path / "paper_state.json"
    pc = PaperClient(starting_capital=200000, fill_mode="market_like", persist_path=str(persist))
    pc.connect()

    def bad_callback(order, delta):
        raise ValueError("simulated callback error")

    pc.on_fill(bad_callback)
    # Should still complete without raising
    o = _make_order(side=OrderSide.BUY, qty=75, tag="QUANT-test")
    placed = pc.place_order(o)
    assert placed.status == OrderStatus.COMPLETE


def test_on_fill_multiple_callbacks_all_fire(tmp_path):
    """All registered callbacks should fire on each fill."""
    persist = tmp_path / "paper_state.json"
    pc = PaperClient(starting_capital=200000, fill_mode="market_like", persist_path=str(persist))
    pc.connect()

    counter = {"a": 0, "b": 0}
    pc.on_fill(lambda o, d: counter.__setitem__("a", counter["a"] + 1))
    pc.on_fill(lambda o, d: counter.__setitem__("b", counter["b"] + 1))

    pc.place_order(_make_order(side=OrderSide.BUY, qty=75, tag="QUANT-test"))
    assert counter == {"a": 1, "b": 1}

    pc.place_order(_make_order(side=OrderSide.SELL, qty=75, price=100.0, tag="CLOSE"))
    assert counter == {"a": 2, "b": 2}
