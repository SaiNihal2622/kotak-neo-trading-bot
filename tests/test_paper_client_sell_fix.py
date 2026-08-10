"""Unit tests for the PaperClient SELL-without-position fix.

Bug (2026-08-10): PaperClient._apply_fill SELL branch only mutated existing
positions. A SELL with no prior position was recorded in orders but no SHORT
was created. Result: 4 ghost LONG positions at EOD.

These tests verify the fix and the various SELL paths.
"""
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# project root
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kotak_bot.broker.paper_client import PaperClient
from kotak_bot.broker.base import (
    Order,
    OrderSide,
    OrderType,
    ProductType,
    Tick,
)


def _make_client(tmpdir: str) -> PaperClient:
    pc = PaperClient(
        starting_capital=100_000.0,
        slippage_bps=0.0,  # no slippage for deterministic tests
        persist_path=str(Path(tmpdir) / "state.json"),
    )
    pc.connect()
    return pc


def _inject_tick(pc: PaperClient, symbol: str, ltp: float) -> None:
    pc.inject_tick(Tick(
        symbol=symbol, exchange="NFO", ltp=ltp, bid=ltp - 0.05, ask=ltp + 0.05,
        volume=0, timestamp=datetime.utcnow(), underlying="NIFTY",
    ))


def _make_order(symbol: str, side: OrderSide, qty: int = 75, price: float = 0.0) -> Order:
    return Order(
        symbol=symbol,
        side=side,
        qty=qty,
        order_type=OrderType.MARKET if price == 0 else OrderType.LIMIT,
        product=ProductType.MIS,
        price=price,
        exchange="NFO",
        strike=24600,
        option_type="CE",
        expiry="2026-08-10",
        underlying="NIFTY",
    )


def test_sell_into_empty_creates_short():
    """The core fix: SELL with no prior position must open a SHORT."""
    with tempfile.TemporaryDirectory() as tmp:
        pc = _make_client(tmp)
        _inject_tick(pc, "NIFTY10AUG2624600CE", 100.0)
        # SELL 75 into nothing
        order = _make_order("NIFTY10AUG2624600CE", OrderSide.SELL, qty=75)
        pc.place_order(order)
        positions = pc.get_positions()
        assert len(positions) == 1, f"expected 1 position, got {len(positions)}"
        pos = positions[0]
        assert pos.symbol == "NIFTY10AUG2624600CE"
        assert pos.qty == -75, f"expected qty=-75 (short), got {pos.qty}"
        assert pos.avg_price == 100.0, f"expected avg=100.0, got {pos.avg_price}"
        print("  PASS: SELL into empty opens SHORT position")


def test_buy_closes_short():
    """BUY 75 to close a SHORT 75 position should net to 0 and remove it."""
    with tempfile.TemporaryDirectory() as tmp:
        pc = _make_client(tmp)
        _inject_tick(pc, "NIFTY10AUG2624400PE", 50.0)
        # open SHORT
        pc.place_order(_make_order("NIFTY10AUG2624400PE", OrderSide.SELL, qty=75))
        assert pc.get_positions()[0].qty == -75
        # close SHORT via BUY
        pc.place_order(_make_order("NIFTY10AUG2624400PE", OrderSide.BUY, qty=75))
        positions = pc.get_positions()
        assert len(positions) == 0, f"expected 0 positions, got {len(positions)}: {positions}"
        print("  PASS: BUY closes SHORT (position removed)")


def test_sell_closes_long():
    """SELL 75 to close a LONG 75 should remove the position and realize P&L."""
    with tempfile.TemporaryDirectory() as tmp:
        pc = _make_client(tmp)
        _inject_tick(pc, "NIFTY10AUG2624600CE", 100.0)
        # open LONG
        pc.place_order(_make_order("NIFTY10AUG2624600CE", OrderSide.BUY, qty=75))
        # mark up
        _inject_tick(pc, "NIFTY10AUG2624600CE", 120.0)
        # close LONG via SELL
        pc.place_order(_make_order("NIFTY10AUG2624600CE", OrderSide.SELL, qty=75))
        positions = pc.get_positions()
        assert len(positions) == 0, f"expected 0 positions, got {len(positions)}"
        # realized PnL: sold at 120, bought at 100, * 75 = +1500
        m = pc.get_margins()
        assert m["realized_pnl"] == 1500.0, f"expected realized=1500, got {m['realized_pnl']}"
        print("  PASS: SELL closes LONG (realizes PnL, position removed)")


def test_sell_adds_to_short():
    """SELL when already SHORT should INCREASE the short position."""
    with tempfile.TemporaryDirectory() as tmp:
        pc = _make_client(tmp)
        _inject_tick(pc, "NIFTY10AUG2624400PE", 50.0)
        # open SHORT 75
        pc.place_order(_make_order("NIFTY10AUG2624400PE", OrderSide.SELL, qty=75))
        # SELL 75 more (add to short)
        pc.place_order(_make_order("NIFTY10AUG2624400PE", OrderSide.SELL, qty=75))
        pos = pc.get_positions()[0]
        assert pos.qty == -150, f"expected qty=-150, got {pos.qty}"
        print("  PASS: SELL adds to existing SHORT")


def test_sell_overshoot_flips_long_to_short():
    """Selling more than held LONG should flip to a SHORT cleanly."""
    with tempfile.TemporaryDirectory() as tmp:
        pc = _make_client(tmp)
        _inject_tick(pc, "NIFTY10AUG2624600CE", 100.0)
        # open LONG 50
        pc.place_order(_make_order("NIFTY10AUG2624600CE", OrderSide.BUY, qty=50))
        # SELL 100 (50 to close, 50 to open SHORT)
        pc.place_order(_make_order("NIFTY10AUG2624600CE", OrderSide.SELL, qty=100))
        pos = pc.get_positions()[0]
        assert pos.qty == -50, f"expected qty=-50 (flipped), got {pos.qty}"
        print("  PASS: SELL > LONG flips cleanly to SHORT")


def test_iron_butterfly_full_cycle():
    """End-to-end: iron butterfly open + EOD close = 0 positions, correct realized PnL."""
    with tempfile.TemporaryDirectory() as tmp:
        pc = _make_client(tmp)
        sym_atm_ce = "NIFTY10AUG2625000CE"
        sym_atm_pe = "NIFTY10AUG2625000PE"
        sym_otm_ce = "NIFTY10AUG2625100CE"
        sym_otm_pe = "NIFTY10AUG2624900PE"
        # short ATM CE @ 100
        _inject_tick(pc, sym_atm_ce, 100.0)
        pc.place_order(_make_order(sym_atm_ce, OrderSide.SELL, qty=75))
        # short ATM PE @ 100
        _inject_tick(pc, sym_atm_pe, 100.0)
        pc.place_order(_make_order(sym_atm_pe, OrderSide.SELL, qty=75))
        # long OTM CE @ 70 (wing)
        _inject_tick(pc, sym_otm_ce, 70.0)
        pc.place_order(_make_order(sym_otm_ce, OrderSide.BUY, qty=75))
        # long OTM PE @ 70 (wing)
        _inject_tick(pc, sym_otm_pe, 70.0)
        pc.place_order(_make_order(sym_otm_pe, OrderSide.BUY, qty=75))
        # check positions: 2 shorts + 2 longs
        positions = {p.symbol: p for p in pc.get_positions()}
        assert positions[sym_atm_ce].qty == -75
        assert positions[sym_atm_pe].qty == -75
        assert positions[sym_otm_ce].qty == +75
        assert positions[sym_otm_pe].qty == +75
        # EOD: market moves, tick up. Now ATM CE/PE cheap out, wings expensive
        _inject_tick(pc, sym_atm_ce, 50.0)
        _inject_tick(pc, sym_atm_pe, 50.0)
        _inject_tick(pc, sym_otm_ce, 100.0)
        _inject_tick(pc, sym_otm_pe, 100.0)
        # EOD close: BUY back shorts, SELL long wings
        pc.place_order(_make_order(sym_atm_ce, OrderSide.BUY, qty=75))
        pc.place_order(_make_order(sym_atm_pe, OrderSide.BUY, qty=75))
        pc.place_order(_make_order(sym_otm_ce, OrderSide.SELL, qty=75))
        pc.place_order(_make_order(sym_otm_pe, OrderSide.SELL, qty=75))
        # all flat
        positions = pc.get_positions()
        assert len(positions) == 0, f"expected 0 positions, got {len(positions)}: {positions}"
        m = pc.get_margins()
        # realized PnL per leg:
        #   short ATM CE: sold 100, bought 50 -> +50 * 75 = +3750
        #   short ATM PE: sold 100, bought 50 -> +50 * 75 = +3750
        #   long OTM CE:  bought 70, sold 100  -> +30 * 75 = +2250
        #   long OTM PE:  bought 70, sold 100  -> +30 * 75 = +2250
        # total = 12000
        assert m["realized_pnl"] == 12000.0, f"expected realized=12000, got {m['realized_pnl']}"
        print(f"  PASS: iron butterfly full cycle, realized = Rs.{m['realized_pnl']:,.0f}")


def test_rebuild_from_orders():
    """rebuild_positions_from_orders should net all COMPLETE orders correctly."""
    with tempfile.TemporaryDirectory() as tmp:
        pc = _make_client(tmp)
        sym = "NIFTY10AUG2624400PE"
        _inject_tick(pc, sym, 50.0)
        # simulate the bug scenario: SELL 30, no pos created (we'll fake it)
        # actually with the fix in place, the SELL creates a SHORT. So we test
        # rebuild on the post-fix state.
        pc.place_order(_make_order(sym, OrderSide.SELL, qty=75))  # SHORT 75
        # partially close
        pc.place_order(_make_order(sym, OrderSide.BUY, qty=30))   # SHORT 45
        # rebuild from orders
        report = pc.rebuild_positions_from_orders()
        # net should still be SHORT 45
        positions = pc.get_positions()
        assert len(positions) == 1
        assert positions[0].qty == -45, f"expected qty=-45 after rebuild, got {positions[0].qty}"
        print(f"  PASS: rebuild_positions_from_orders net = {positions[0].qty}")


if __name__ == "__main__":
    tests = [
        test_sell_into_empty_creates_short,
        test_buy_closes_short,
        test_sell_closes_long,
        test_sell_adds_to_short,
        test_sell_overshoot_flips_long_to_short,
        test_iron_butterfly_full_cycle,
        test_rebuild_from_orders,
    ]
    failed = 0
    for t in tests:
        try:
            print(f"\n{t.__name__}:")
            t()
        except AssertionError as e:
            print(f"  FAIL: {e}")
            failed += 1
        except Exception as e:
            import traceback
            traceback.print_exc()
            failed += 1
    print(f"\n{len(tests) - failed}/{len(tests)} tests passed")
    sys.exit(0 if failed == 0 else 1)
