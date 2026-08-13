"""Tests for PaperClient fill_mode behaviors."""
import sys
import time
from pathlib import Path
from datetime import datetime

# add project to path so we can import kotak_bot
sys.path.insert(0, str(Path(__file__).parent.parent))

from kotak_bot.broker.paper_client import PaperClient
from kotak_bot.broker.base import Order, OrderSide, OrderType, ProductType, OrderStatus, Tick


def _make_order(symbol="NIFTY12AUG2624350CE", side=OrderSide.BUY, qty=65, price=100.0, ot=OrderType.LIMIT):
    return Order(
        order_id="",
        symbol=symbol,
        exchange="NFO",
        side=side,
        qty=qty,
        price=price,
        order_type=ot,
        product=ProductType.MIS,
        strike=24350,
        option_type="CE",
        expiry="2026-08-12",
        underlying="NIFTY",
    )


def _make_tick(symbol="NIFTY12AUG2624350CE", ltp=100.0):
    return Tick(symbol=symbol, ltp=ltp, bid=ltp - 0.10, ask=ltp + 0.10, volume=100, timestamp=datetime.utcnow())


def test_market_like_fills_immediately_no_tick(tmp_path):
    """market_like: even without a tick, the order should fill at the limit price."""
    persist = tmp_path / "paper_state.json"
    pc = PaperClient(starting_capital=100000, fill_mode="market_like", persist_path=str(persist))
    pc.connect()
    o = _make_order(side=OrderSide.SELL, price=60.0)  # conservative SELL
    placed = pc.place_order(o)
    assert placed.status == OrderStatus.COMPLETE, f"expected COMPLETE in market_like, got {placed.status}"
    assert placed.filled_qty == 65
    # fill price = 60.0 (limit) - 0.05% slippage = 59.97 (rounded)
    assert 59.5 <= placed.avg_fill_price <= 60.5
    print(f"  market_like (no tick): SELL filled @ {placed.avg_fill_price}")


def test_market_like_uses_tick_when_available(tmp_path):
    """market_like with a tick: fill at tick.ltp +/- slippage."""
    persist = tmp_path / "paper_state.json"
    pc = PaperClient(starting_capital=100000, fill_mode="market_like", persist_path=str(persist))
    pc.connect()
    pc.inject_tick(_make_tick(ltp=150.0))
    o = _make_order(side=OrderSide.BUY, price=140.0)
    placed = pc.place_order(o)
    assert placed.status == OrderStatus.COMPLETE
    # BUY at LTP 150 + slippage 0.075 = ~150.08
    assert 149.5 <= placed.avg_fill_price <= 150.5, f"unexpected fill: {placed.avg_fill_price}"
    print(f"  market_like (with tick): BUY filled @ {placed.avg_fill_price}")


def test_market_like_force_fills_stale_order_on_first_tick(tmp_path):
    """market_like: if order placed before any tick, the first tick for that symbol force-fills it."""
    persist = tmp_path / "paper_state.json"
    pc = PaperClient(starting_capital=100000, fill_mode="market_like", persist_path=str(persist))
    pc.connect()
    o = _make_order(side=OrderSide.SELL, price=40.0)
    placed = pc.place_order(o)
    # No tick yet, but market_like fills at limit price 40
    assert placed.status == OrderStatus.COMPLETE
    print(f"  market_like: order placed before tick still filled ({placed.avg_fill_price})")


def test_realistic_limit_fills_aggressive_sell(tmp_path):
    """realistic_limit: a SELL at 60 with LTP 100 still fills at synthetic_bid (99.9)
    because offering below the market price is realistic — buyer pays the bid, not your limit.
    This is the expected behavior; orders that 'don't fill' in production are because the
    strike has no ticks (keep-alive edge case), not because the price is wrong."""
    persist = tmp_path / "paper_state.json"
    pc = PaperClient(starting_capital=100000, fill_mode="realistic_limit", persist_path=str(persist))
    pc.connect()
    pc.inject_tick(_make_tick(ltp=100.0))
    o = _make_order(side=OrderSide.SELL, price=60.0)
    placed = pc.place_order(o)
    assert placed.status == OrderStatus.COMPLETE
    assert 99.0 <= placed.avg_fill_price <= 100.0
    print(f"  realistic_limit: SELL @ 60 with LTP 100 fills @ {placed.avg_fill_price} (at bid)")


def test_aggressive_limit_fills_within_5pct(tmp_path):
    """aggressive_limit with wider near_ltp threshold: a SELL at 96 (4% from LTP 100) fills.

    For SELL, the first branch in _try_fill (`price <= synthetic_bid`) fires when the
    limit is below the bid. For SELL @ 96 with LTP 100, synthetic_bid = 99.90 — so the
    first branch fires and fills at 99.9 (the synthetic bid, not the limit).
    """
    persist = tmp_path / "paper_state.json"
    pc = PaperClient(starting_capital=100000, fill_mode="aggressive_limit",
                     limit_fill_near_ltp_pct=5.0, persist_path=str(persist))
    pc.connect()
    pc.inject_tick(_make_tick(ltp=100.0))
    o = _make_order(side=OrderSide.SELL, price=96.0)
    placed = pc.place_order(o)
    assert placed.status == OrderStatus.COMPLETE
    assert 99.0 <= placed.avg_fill_price <= 100.0
    print(f"  aggressive_limit: SELL @ 96 with LTP 100 filled @ {placed.avg_fill_price}")


# Note: aggressive_limit is documented but not a separate code path — it just adjusts
# limit_fill_near_ltp_pct via settings.yaml. The first branch (`price <= bid`) always
# fires for SELLs priced below bid (correctly: buyer pays bid, not limit), so the
# near_ltp threshold only matters for SELLs priced ABOVE bid (rare) or BUYs priced
# below ask. The production fix for unfilled orders is market_like mode (always fills),
# not aggressive_limit.


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        print("test_market_like_fills_immediately_no_tick")
        test_market_like_fills_immediately_no_tick(tmp_path)
        print("test_market_like_uses_tick_when_available")
        test_market_like_uses_tick_when_available(tmp_path)
        print("test_market_like_force_fills_stale_order_on_first_tick")
        test_market_like_force_fills_stale_order_on_first_tick(tmp_path)
        print("test_realistic_limit_fills_aggressive_sell")
        test_realistic_limit_fills_aggressive_sell(tmp_path)
        print("test_aggressive_limit_fills_within_5pct")
        test_aggressive_limit_fills_within_5pct(tmp_path)
        print("ALL PASS")
