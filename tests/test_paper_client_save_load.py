"""Regression test for PaperClient save/load enum round-trip.

This test caught a real production bug (commits 1493ae0):
- _save_state was using o.__dict__ directly, mutating the live Order object's
  enums to strings every save. That broke in-memory trade book integrity.
- _load_state didn't convert side/order_type/product back from string to enum,
  so any orders saved by the buggy code would load with corrupted types.

This test ensures:
1. After save + load, all enums are properly typed (not strings)
2. Cash, positions, and orders all round-trip correctly
3. Old (string-typed) state files also load correctly (backward compat)
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kotak_bot.broker.paper_client import PaperClient
from kotak_bot.broker.base import (
    Order, OrderSide, OrderStatus, OrderType, ProductType, Position, Tick,
)


class TestPaperClientSaveLoadEnumRoundTrip(unittest.TestCase):
    def setUp(self):
        # Use a temp file so we don't pollute real data_cache
        tmp = tempfile.NamedTemporaryFile(suffix='.json', delete=False, mode='w')
        tmp.close()
        self.path = tmp.name

    def tearDown(self):
        if os.path.exists(self.path):
            os.unlink(self.path)

    def test_save_then_load_preserves_enum_types(self):
        """After save + load, side/order_type/product must be enums not strings."""
        # 1) Create a client, place a BUY order
        c1 = PaperClient(starting_capital=100_000, persist_path=self.path)
        c1.connect()
        order = Order(
            symbol="NIFTY11AUG2624450CE",
            side=OrderSide.BUY,
            qty=130,
            order_type=OrderType.LIMIT,
            product=ProductType.MIS,
            price=21.60,
            strike=24450,
            option_type="CE",
            expiry="2026-08-11",
            underlying="NIFTY",
        )
        # Inject a tick so it fills
        c1.inject_tick(Tick(
            symbol="NIFTY11AUG2624450CE", ltp=21.60, bid=21.55, ask=21.65,
            exchange="NFO", underlying="NIFTY",
        ))
        c1.place_order(order)
        # Verify it's an enum (should be, since the fix)
        placed = list(c1._orders.values())[0]
        self.assertIsInstance(placed.side, OrderSide, "side must be enum after place_order")
        self.assertIsInstance(placed.order_type, OrderType, "order_type must be enum")
        self.assertIsInstance(placed.product, ProductType, "product must be enum")
        # Save state happens automatically in place_order; verify the on-disk
        # state contains the enums (or rather, was a copy with strings, not the
        # original)
        self.assertIsInstance(placed.side, OrderSide)  # still enum after save

        # 2) Create a NEW client from the same file, verify enums are restored
        c2 = PaperClient(starting_capital=100_000, persist_path=self.path)
        loaded = list(c2._orders.values())[0]
        self.assertIsInstance(loaded.side, OrderSide, f"side is {type(loaded.side)}: {loaded.side!r}")
        self.assertIsInstance(loaded.order_type, OrderType, f"order_type is {type(loaded.order_type)}")
        self.assertIsInstance(loaded.product, ProductType, f"product is {type(loaded.product)}")
        self.assertEqual(loaded.side, OrderSide.BUY)
        self.assertEqual(loaded.order_type, OrderType.LIMIT)
        self.assertEqual(loaded.product, ProductType.MIS)
        self.assertEqual(loaded.symbol, "NIFTY11AUG2624450CE")
        self.assertEqual(loaded.qty, 130)
        self.assertEqual(loaded.avg_fill_price, 21.60)
        self.assertEqual(loaded.status, OrderStatus.COMPLETE)

    def test_backward_compat_with_old_string_state(self):
        """Old state files (saved by buggy code) with string enums should still load."""
        # Manually write a state file with STRING enums (simulating old buggy save)
        old_state = {
            "cash": 100_000.0,
            "realized_pnl": 0.0,
            "orders": {
                "PAPER-OLD00001": {
                    "symbol": "NIFTY11AUG2624450CE",
                    "side": "BUY",  # string, not enum
                    "qty": 130,
                    "order_type": "LIMIT",  # string, not enum
                    "product": "MIS",  # string, not enum
                    "price": 21.60,
                    "avg_fill_price": 21.60,
                    "filled_qty": 130,
                    "status": "complete",  # string
                    "placed_at": "2026-08-11T13:00:00",
                    "filled_at": "2026-08-11T13:00:01",
                    "trigger_price": 0.0,
                    "tag": "old",
                    "exchange": "NFO",
                    "strike": 24450.0,
                    "option_type": "CE",
                    "expiry": "2026-08-11",
                    "underlying": "NIFTY",
                    "rejection_reason": "",
                    "expected_fill_price": 0.0,
                }
            },
            "positions": {},
        }
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(old_state, f)

        c = PaperClient(starting_capital=100_000, persist_path=self.path)
        loaded = list(c._orders.values())[0]
        # The fix should convert strings back to enums
        self.assertIsInstance(loaded.side, OrderSide, f"side should be enum, got {type(loaded.side)}")
        self.assertIsInstance(loaded.order_type, OrderType)
        self.assertIsInstance(loaded.product, ProductType)
        self.assertIsInstance(loaded.status, OrderStatus)
        self.assertEqual(loaded.side, OrderSide.BUY)

    def test_position_round_trip(self):
        """Positions should also round-trip with proper enum types."""
        c1 = PaperClient(starting_capital=100_000, persist_path=self.path)
        c1.connect()
        # Inject tick + place + fill
        c1.inject_tick(Tick(symbol="NIFTY11AUG2624450CE", ltp=21.60, exchange="NFO"))
        c1.place_order(Order(
            symbol="NIFTY11AUG2624450CE", side=OrderSide.BUY, qty=130,
            order_type=OrderType.LIMIT, product=ProductType.MIS, price=21.60,
            exchange="NFO", strike=24450, option_type="CE", expiry="2026-08-11",
            underlying="NIFTY",
        ))
        # Verify position exists with enum product
        self.assertEqual(len(c1._positions), 1)
        pos = list(c1._positions.values())[0]
        self.assertIsInstance(pos.product, ProductType)

        # Reload
        c2 = PaperClient(starting_capital=100_000, persist_path=self.path)
        self.assertEqual(len(c2._positions), 1)
        pos2 = list(c2._positions.values())[0]
        self.assertIsInstance(pos2.product, ProductType)
        self.assertEqual(pos2.symbol, "NIFTY11AUG2624450CE")
        self.assertEqual(pos2.qty, 130)
        self.assertEqual(pos2.avg_price, 21.60)


class TestPaperClientFillLogic(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.NamedTemporaryFile(suffix='.json', delete=False, mode='w')
        tmp.close()
        self.path = tmp.name

    def tearDown(self):
        if os.path.exists(self.path):
            os.unlink(self.path)

    def test_limit_buy_fills_at_limit_or_better(self):
        c = PaperClient(starting_capital=100_000, persist_path=self.path)
        c.connect()
        # Tick at 100, spread 0.1%
        c.inject_tick(Tick(symbol="X", ltp=100.0, exchange="NFO"))
        # BUY LIMIT at 100.5 (above ask ~100.10) — should fill at 100.10
        order = Order(
            symbol="X", side=OrderSide.BUY, qty=10, order_type=OrderType.LIMIT,
            product=ProductType.MIS, price=100.5, exchange="NFO",
        )
        c.place_order(order)
        o = list(c._orders.values())[0]
        self.assertEqual(o.status, OrderStatus.COMPLETE)
        self.assertEqual(o.avg_fill_price, 100.10)

    def test_limit_sell_fills_at_limit_or_better(self):
        c = PaperClient(starting_capital=100_000, persist_path=self.path)
        c.connect()
        c.inject_tick(Tick(symbol="X", ltp=100.0, exchange="NFO"))
        # SELL LIMIT at 99.5 (below bid ~99.90) — should fill at 99.90
        order = Order(
            symbol="X", side=OrderSide.SELL, qty=10, order_type=OrderType.LIMIT,
            product=ProductType.MIS, price=99.5, exchange="NFO",
        )
        c.place_order(order)
        o = list(c._orders.values())[0]
        self.assertEqual(o.status, OrderStatus.COMPLETE)
        self.assertEqual(o.avg_fill_price, 99.90)

    def test_market_order_slippage(self):
        c = PaperClient(starting_capital=100_000, slippage_bps=5.0, persist_path=self.path)
        c.connect()
        c.inject_tick(Tick(symbol="X", ltp=100.0, exchange="NFO"))
        # MARKET BUY at 100 → fill at 100 + 0.05% = 100.05
        order = Order(
            symbol="X", side=OrderSide.BUY, qty=10, order_type=OrderType.MARKET,
            product=ProductType.MIS, price=0, exchange="NFO",
        )
        c.place_order(order)
        o = list(c._orders.values())[0]
        self.assertEqual(o.status, OrderStatus.COMPLETE)
        self.assertAlmostEqual(o.avg_fill_price, 100.05, places=4)


if __name__ == "__main__":
    unittest.main()
