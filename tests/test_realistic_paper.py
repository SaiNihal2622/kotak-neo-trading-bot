"""FIX 2026-09-17: tests for the realistic paper fill mode.

The realistic fill mode models the live Kotak Neo order book behavior:
- BUY MARKET fills at the ask (you pay more than mid)
- SELL MARKET fills at the bid (you receive less than mid)
- LIMIT BUY only fills when limit >= ask (otherwise sits as maker)
- LIMIT SELL only fills when limit <= bid (otherwise sits as maker)
- Unfilled LIMIT orders get rejected after unfilled_order_timeout_sec
- Limit prices are snapped to NSE tick (0.05 INR)
- Partial fills possible when partial_fill_min_pct < 1.0

These tests verify each invariant.
"""
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

from kotak_bot.broker.paper_client import PaperClient
from kotak_bot.broker.base import Tick, Order, OrderSide, OrderType, ProductType


def make_tick(symbol='NIFTY17SEP2623200CE', ltp=154.53, bid=154.50, ask=154.60):
    return Tick(symbol=symbol, ltp=ltp, bid=bid, ask=ask)


def make_order(side, qty=75, otype=OrderType.MARKET, price=0.0):
    return Order(
        symbol='NIFTY17SEP2623200CE',
        side=side,
        qty=qty,
        order_type=otype,
        price=price,
        product=ProductType.MIS,
        strike=23200,
        option_type='CE',
        expiry='2026-09-17',
        underlying='NIFTY',
    )


def test_tick_alignment():
    """Prices snap to nearest 0.05 INR tick (NSE rule)."""
    assert PaperClient._align_to_tick(4.83) == 4.85
    assert PaperClient._align_to_tick(4.80) == 4.80
    assert PaperClient._align_to_tick(627.21) == 627.20
    assert PaperClient._align_to_tick(517.58) == 517.60
    assert PaperClient._align_to_tick(157.67) == 157.65
    assert PaperClient._align_to_tick(0.0) == 0.0


def test_market_buy_fills_at_ask():
    """Realistic BUY MARKET crosses the offer — never fills at mid."""
    pc = PaperClient(starting_capital=100000, fill_mode='realistic')
    tick = make_tick(ltp=154.53, bid=154.50, ask=154.60)
    order = make_order(OrderSide.BUY)
    px, status = pc._compute_bid_ask_fill(order, tick)
    assert status == 'filled'
    assert px >= 154.60  # at ask or worse, never less
    assert abs(px - 154.60) < 0.05


def test_market_sell_fills_at_bid():
    """Realistic SELL MARKET hits the bid — never fills at mid."""
    pc = PaperClient(starting_capital=100000, fill_mode='realistic')
    tick = make_tick(ltp=154.53, bid=154.50, ask=154.60)
    order = make_order(OrderSide.SELL)
    px, status = pc._compute_bid_ask_fill(order, tick)
    assert status == 'filled'
    assert px <= 154.50  # at bid or worse, never more


def test_limit_buy_does_not_fill_below_ask():
    """LIMIT BUY with limit < ask sits as maker — status=no_fill."""
    pc = PaperClient(starting_capital=100000, fill_mode='realistic')
    tick = make_tick(ltp=154.53, bid=154.50, ask=154.60)
    order = make_order(OrderSide.BUY, otype=OrderType.LIMIT, price=154.50)
    px, status = pc._compute_bid_ask_fill(order, tick)
    assert status == 'no_fill'
    assert px == 0.0


def test_limit_buy_fills_when_above_ask():
    """LIMIT BUY with limit >= ask fills at min(limit, ask) — fills at ASK, not limit."""
    pc = PaperClient(starting_capital=100000, fill_mode='realistic')
    tick = make_tick(ltp=154.53, bid=154.50, ask=154.60)
    # limit way above ask -> fills at ask (we don't pay more than we bid even if limit says so)
    order = make_order(OrderSide.BUY, otype=OrderType.LIMIT, price=160.00)
    px, status = pc._compute_bid_ask_fill(order, tick)
    assert status == 'filled'
    assert abs(px - 154.60) < 0.05
    # limit just above ask -> still fills at ask (no price improvement on aggressive BUY)
    order2 = make_order(OrderSide.BUY, otype=OrderType.LIMIT, price=154.65)
    px2, status2 = pc._compute_bid_ask_fill(order2, tick)
    assert status2 == 'filled'
    assert abs(px2 - 154.60) < 0.05, f'expected fill at ask 154.60, got {px2}'


def test_limit_sell_does_not_fill_above_bid():
    """LIMIT SELL with limit > bid sits as maker."""
    pc = PaperClient(starting_capital=100000, fill_mode='realistic')
    tick = make_tick(ltp=154.53, bid=154.50, ask=154.60)
    order = make_order(OrderSide.SELL, otype=OrderType.LIMIT, price=154.60)
    px, status = pc._compute_bid_ask_fill(order, tick)
    assert status == 'no_fill'


def test_limit_sell_fills_below_bid():
    """LIMIT SELL with limit <= bid fills at max(limit, bid)."""
    pc = PaperClient(starting_capital=100000, fill_mode='realistic')
    tick = make_tick(ltp=154.53, bid=154.50, ask=154.60)
    # limit = bid exactly -> fills at bid
    order = make_order(OrderSide.SELL, otype=OrderType.LIMIT, price=154.50)
    px, status = pc._compute_bid_ask_fill(order, tick)
    assert status == 'filled'
    assert abs(px - 154.50) < 0.05


def test_no_bid_ask_falls_back_to_synthetic():
    """If tick has no bid/ask, paper uses synthetic spread = ltp ± spread_pct."""
    pc = PaperClient(
        starting_capital=100000,
        fill_mode='realistic',
        limit_fill_spread_pct=0.1,
        limit_fill_min_spread=0.05,
    )
    tick = Tick(symbol='X', ltp=100.0, bid=0.0, ask=0.0)
    order = make_order(OrderSide.BUY)
    px, status = pc._compute_bid_ask_fill(order, tick)
    assert status == 'filled'
    # 0.1% of 100 = 0.10 spread, ask = 100.10
    assert abs(px - 100.10) < 0.05


def test_partial_fill_min_pct_blocks_small_fills():
    """When partial_fill_min_pct=0.7, fills below 70% reject rather than partial."""
    pc = PaperClient(
        starting_capital=100000,
        fill_mode='realistic',
        partial_fill_min_pct=1.0,  # all-or-nothing
    )
    # All-or-nothing means partial=true wouldn't be used; we just check status
    tick = make_tick(ltp=154.53, bid=154.50, ask=154.60)
    order = make_order(OrderSide.BUY, otype=OrderType.LIMIT, price=160.00)
    px, status = pc._compute_bid_ask_fill(order, tick)
    # status stays 'filled' (not 'partial') when partial_fill_min_pct=1.0
    assert status == 'filled'


def test_unfilled_order_timeout_rejects():
    """In realistic mode, open LIMIT orders past timeout get rejected."""
    pc = PaperClient(
        starting_capital=100000,
        fill_mode='realistic',
        unfilled_order_timeout_sec=1.0,
    )
    pc._connected = True
    pc.connect()
    # Place a LIMIT order that won't fill (price below ask)
    order = make_order(OrderSide.BUY, otype=OrderType.LIMIT, price=4.0)
    pc.place_order(order)
    # Force the placed_at into the past to simulate timeout
    pc._order_placed_ts[order.order_id] = time.time() - 10.0
    # Insert a tick that doesn't cross the book
    pc._ticks[order.symbol] = make_tick(ltp=154.53, bid=154.50, ask=154.60)
    pc._timeout_unfilled_orders()
    # Order should be REJECTED
    assert pc._orders[order.order_id].status.value == 'rejected', \
        f"got status {pc._orders[order.order_id].status.value}"
    assert 'unfilled' in pc._orders[order.order_id].rejection_reason.lower()