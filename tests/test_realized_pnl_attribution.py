"""Tests for per-trade realized P&L attribution in OrderManager.

Bug context: `OrderManager.close_trade()` historically placed close orders
but never computed or persisted `trade.realized_pnl`, so closed trades in
`trades_state.json` showed `realized_pnl: 0.0` even when the broker's
cumulative P&L was clearly non-zero (e.g. -Rs.55 on 2026-08-24 Monday paper
session). This made per-strategy attribution, drawdown tracking, and
strategy-level kill-switches impossible.

Fix: `close_trade` now computes per-leg P&L from entry fill vs close fill
and writes the sum to `trade.realized_pnl`. A `backfill_realized_pnl()`
method recomputes it for any historical trade closed before the fix.
"""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kotak_bot.broker.base import (
    Order, OrderSide, OrderStatus, OrderType, ProductType, Tick,
)
from kotak_bot.broker.paper_client import PaperClient
from kotak_bot.execution.order_manager import OrderManager
from kotak_bot.strategy.base import StrategyName, TradePlan


def _inject_tick(pc: PaperClient, symbol: str, ltp: float) -> None:
    pc.inject_tick(Tick(
        symbol=symbol, exchange="NFO", ltp=ltp, bid=ltp - 0.05, ask=ltp + 0.05,
        volume=0, timestamp=datetime.now(timezone.utc), underlying="NIFTY",
    ))


def _make_pc(tmpdir: str) -> PaperClient:
    pc = PaperClient(
        starting_capital=100_000.0,
        slippage_bps=0.0,
        persist_path=str(Path(tmpdir) / "state.json"),
    )
    pc.connect()
    return pc


# ----------------------------------------------------------------------------
# Test 1: Single-leg BUY — P&L = (exit - entry) * qty
# ----------------------------------------------------------------------------
def test_single_leg_buy_profit():
    """BUY 75 @ 100, close at 110 → +Rs.750 realized."""
    with tempfile.TemporaryDirectory() as tmp:
        pc = _make_pc(tmp)
        sym = "NIFTY10AUG2625000CE"
        _inject_tick(pc, sym, 100.0)
        mgr = OrderManager(pc, persist_path=str(Path(tmp) / "trades.json"))
        plan = TradePlan(
            strategy=StrategyName.DIRECTIONAL_DEBIT, underlying="NIFTY",
            legs=[{"side": "BUY", "strike": 25000, "opt_type": "CE", "qty": 1,
                   "order_type": "MARKET", "price": 100.0, "tag": "test"}],
            target=150.0, stop=50.0, confidence=0.8, reason="test",
        )
        trade = mgr.execute_plan(plan, qty=1, expiry="2026-08-10",
                                 lot_sizes={"NIFTY": 75}, use_bracket=False)
        assert len(trade.orders) == 1
        assert trade.orders[0].status == OrderStatus.COMPLETE
        assert trade.orders[0].avg_fill_price == 100.0
        # Update LTP to 110 (profit scenario) before close
        _inject_tick(pc, sym, 110.0)
        mgr.close_trade(trade.trade_id, reason="take_profit")
        # 75 * (110 - 100) = 750
        assert trade.realized_pnl == 750.0, \
            f"expected 750.0, got {trade.realized_pnl}"
        # Reload from disk and verify persistence
        mgr2 = OrderManager(pc, persist_path=str(Path(tmp) / "trades.json"))
        loaded = list(mgr2._trades.values())[0]
        assert loaded.realized_pnl == 750.0, \
            f"persisted realized_pnl wrong: {loaded.realized_pnl}"
        print(f"  PASS: single-leg BUY profit +Rs.{trade.realized_pnl}")


# ----------------------------------------------------------------------------
# Test 2: Single-leg BUY — P&L = (exit - entry) * qty (loss)
# ----------------------------------------------------------------------------
def test_single_leg_buy_loss():
    """BUY 75 @ 100, close at 90 → -Rs.750 realized."""
    with tempfile.TemporaryDirectory() as tmp:
        pc = _make_pc(tmp)
        sym = "NIFTY10AUG2625000CE"
        _inject_tick(pc, sym, 100.0)
        mgr = OrderManager(pc, persist_path=str(Path(tmp) / "trades.json"))
        plan = TradePlan(
            strategy=StrategyName.DIRECTIONAL_DEBIT, underlying="NIFTY",
            legs=[{"side": "BUY", "strike": 25000, "opt_type": "CE", "qty": 1,
                   "order_type": "MARKET", "price": 100.0, "tag": "test"}],
            target=150.0, stop=50.0, confidence=0.8, reason="test",
        )
        trade = mgr.execute_plan(plan, qty=1, expiry="2026-08-10",
                                 lot_sizes={"NIFTY": 75}, use_bracket=False)
        _inject_tick(pc, sym, 90.0)
        mgr.close_trade(trade.trade_id, reason="stop_loss")
        # 75 * (90 - 100) = -750
        assert trade.realized_pnl == -750.0, \
            f"expected -750.0, got {trade.realized_pnl}"
        print(f"  PASS: single-leg BUY loss Rs.{trade.realized_pnl}")


# ----------------------------------------------------------------------------
# Test 3: Multi-leg iron condor — sum of all 4 legs
# ----------------------------------------------------------------------------
def test_iron_condor_4leg():
    """SELL 65 @ 100, BUY 65 @ 50, SELL 65 @ 80, BUY 65 @ 40.
    Close at 60/20/50/20 (still in profit zone).
    Per-leg P&L (BUY side: exit-entry, SELL side: entry-exit):
      - SELL sc: (100-60)*65 = +2600
      - BUY  lc: (20-50)*65  = -1950
      - SELL sp: (80-50)*65  = +1950
      - BUY  lp: (20-40)*65  = -1300
    Total = +1300
    """
    with tempfile.TemporaryDirectory() as tmp:
        pc = _make_pc(tmp)
        for sym, ltp in [
            ("NIFTY10AUG2624600CE", 100.0),
            ("NIFTY10AUG2624700CE", 50.0),
            ("NIFTY10AUG2624400PE", 80.0),
            ("NIFTY10AUG2624300PE", 40.0),
        ]:
            _inject_tick(pc, sym, ltp)
        mgr = OrderManager(pc, persist_path=str(Path(tmp) / "trades.json"))
        plan = TradePlan(
            strategy=StrategyName.IRON_CONDOR, underlying="NIFTY",
            legs=[
                {"side": "SELL", "strike": 24600, "opt_type": "CE", "qty": 1,
                 "order_type": "MARKET", "price": 100.0, "tag": "ic_NIFTY_sc"},
                {"side": "BUY",  "strike": 24700, "opt_type": "CE", "qty": 1,
                 "order_type": "MARKET", "price": 50.0,  "tag": "ic_NIFTY_lc"},
                {"side": "SELL", "strike": 24400, "opt_type": "PE", "qty": 1,
                 "order_type": "MARKET", "price": 80.0,  "tag": "ic_NIFTY_sp"},
                {"side": "BUY",  "strike": 24300, "opt_type": "PE", "qty": 1,
                 "order_type": "MARKET", "price": 40.0,  "tag": "ic_NIFTY_lp"},
            ],
            target=30.0, stop=300.0, confidence=0.7, reason="test condor",
        )
        trade = mgr.execute_plan(plan, qty=1, expiry="2026-08-10",
                                 lot_sizes={"NIFTY": 65}, use_bracket=False)
        # Update ticks to exit prices
        for sym, ltp in [
            ("NIFTY10AUG2624600CE", 60.0),
            ("NIFTY10AUG2624700CE", 20.0),
            ("NIFTY10AUG2624400PE", 50.0),
            ("NIFTY10AUG2624300PE", 20.0),
        ]:
            _inject_tick(pc, sym, ltp)
        mgr.close_trade(trade.trade_id, reason="eod_square_off")
        expected = (100-60)*65 + (20-50)*65 + (80-50)*65 + (20-40)*65
        # = 2600 - 1950 + 1950 - 1300 = 1300
        assert trade.realized_pnl == round(expected, 2), \
            f"expected {expected}, got {trade.realized_pnl}"
        print(f"  PASS: 4-leg iron condor realized Rs.{trade.realized_pnl}")


# ----------------------------------------------------------------------------
# Test 4: SELL leg close (short) — profit when price drops
# ----------------------------------------------------------------------------
def test_sell_leg_profit():
    """SELL 30 @ 200, close at 150 (price dropped, short profits).
    P&L = (entry - exit) * qty = (200-150)*30 = +1500.
    """
    with tempfile.TemporaryDirectory() as tmp:
        pc = _make_pc(tmp)
        sym = "BANKNIFTY10AUG2657600CE"
        _inject_tick(pc, sym, 200.0)
        mgr = OrderManager(pc, persist_path=str(Path(tmp) / "trades.json"))
        plan = TradePlan(
            strategy=StrategyName.DIRECTIONAL_DEBIT, underlying="BANKNIFTY",
            legs=[{"side": "SELL", "strike": 57600, "opt_type": "CE", "qty": 1,
                   "order_type": "MARKET", "price": 200.0, "tag": "test_short"}],
            target=100.0, stop=400.0, confidence=0.7, reason="test short",
        )
        trade = mgr.execute_plan(plan, qty=1, expiry="2026-08-10",
                                 lot_sizes={"BANKNIFTY": 30}, use_bracket=False)
        _inject_tick(pc, sym, 150.0)
        mgr.close_trade(trade.trade_id, reason="take_profit")
        # (200 - 150) * 30 = 1500
        assert trade.realized_pnl == 1500.0, \
            f"expected 1500.0, got {trade.realized_pnl}"
        print(f"  PASS: SELL leg profit +Rs.{trade.realized_pnl}")


# ----------------------------------------------------------------------------
# Test 5: Backfill repairs historical trades with realized_pnl=0.0
# ----------------------------------------------------------------------------
def test_backfill_repairs_zero_pnl():
    """Simulate a trade that was closed BEFORE the attribution fix.
    Its order book has entry+close orders with fills, but realized_pnl=0.0.
    backfill_realized_pnl() should fix it.
    """
    with tempfile.TemporaryDirectory() as tmp:
        pc = _make_pc(tmp)
        sym = "NIFTY10AUG2625000CE"
        _inject_tick(pc, sym, 100.0)
        mgr = OrderManager(pc, persist_path=str(Path(tmp) / "trades.json"))
        plan = TradePlan(
            strategy=StrategyName.DIRECTIONAL_DEBIT, underlying="NIFTY",
            legs=[{"side": "BUY", "strike": 25000, "opt_type": "CE", "qty": 1,
                   "order_type": "MARKET", "price": 100.0, "tag": "test"}],
            target=150.0, stop=50.0, confidence=0.8, reason="test",
        )
        trade = mgr.execute_plan(plan, qty=1, expiry="2026-08-10",
                                 lot_sizes={"NIFTY": 75}, use_bracket=False)
        _inject_tick(pc, sym, 120.0)
        mgr.close_trade(trade.trade_id, reason="take_profit")
        # Sanity: the new attribution wrote +1500
        assert trade.realized_pnl == 1500.0

        # Now simulate the bug: zero out realized_pnl as if pre-fix code wrote it
        trade.realized_pnl = 0.0
        mgr._save_state()

        # Reload — realized_pnl should be 0.0 (still broken from disk)
        mgr2 = OrderManager(pc, persist_path=str(Path(tmp) / "trades.json"))
        loaded = list(mgr2._trades.values())[0]
        assert loaded.realized_pnl == 0.0, "expected pre-fix 0.0"

        # Run backfill — should fix it
        n_fixed = mgr2.backfill_realized_pnl()
        assert n_fixed == 1, f"expected 1 trade backfilled, got {n_fixed}"
        assert loaded.realized_pnl == 1500.0, \
            f"backfill failed: realized_pnl={loaded.realized_pnl}"

        # Reload after backfill save — should persist
        mgr3 = OrderManager(pc, persist_path=str(Path(tmp) / "trades.json"))
        loaded2 = list(mgr3._trades.values())[0]
        assert loaded2.realized_pnl == 1500.0, \
            f"backfill not persisted: realized_pnl={loaded2.realized_pnl}"
        print(f"  PASS: backfill repaired realized_pnl 0.0 -> 1500.0")


# ----------------------------------------------------------------------------
# Test 6: square_off_all assigns realized_pnl to all closed trades
# ----------------------------------------------------------------------------
def test_square_off_all_multi_trade():
    """Two independent trades, both closed via square_off_all() with
    distinct P&L, both must have correct attribution."""
    with tempfile.TemporaryDirectory() as tmp:
        pc = _make_pc(tmp)
        _inject_tick(pc, "NIFTY10AUG2625000CE", 100.0)
        _inject_tick(pc, "BANKNIFTY10AUG2657600CE", 200.0)
        mgr = OrderManager(pc, persist_path=str(Path(tmp) / "trades.json"))

        plan_a = TradePlan(
            strategy=StrategyName.DIRECTIONAL_DEBIT, underlying="NIFTY",
            legs=[{"side": "BUY", "strike": 25000, "opt_type": "CE", "qty": 1,
                   "order_type": "MARKET", "price": 100.0, "tag": "a"}],
            target=150.0, stop=50.0, confidence=0.8, reason="a",
        )
        plan_b = TradePlan(
            strategy=StrategyName.DIRECTIONAL_DEBIT, underlying="BANKNIFTY",
            legs=[{"side": "BUY", "strike": 57600, "opt_type": "CE", "qty": 1,
                   "order_type": "MARKET", "price": 200.0, "tag": "b"}],
            target=300.0, stop=100.0, confidence=0.8, reason="b",
        )
        trade_a = mgr.execute_plan(plan_a, qty=1, expiry="2026-08-10",
                                    lot_sizes={"NIFTY": 75}, use_bracket=False)
        trade_b = mgr.execute_plan(plan_b, qty=1, expiry="2026-08-10",
                                    lot_sizes={"BANKNIFTY": 30}, use_bracket=False)

        # Update ticks: trade_a profitable (+10), trade_b loss (-20)
        _inject_tick(pc, "NIFTY10AUG2625000CE", 110.0)
        _inject_tick(pc, "BANKNIFTY10AUG2657600CE", 180.0)
        n_closed = mgr.square_off_all(reason="eod")
        assert n_closed == 2

        # Reload from disk
        mgr2 = OrderManager(pc, persist_path=str(Path(tmp) / "trades.json"))
        loaded = {t.trade_id: t for t in mgr2._trades.values()}
        # Trade A: 75 * (110-100) = +750
        # Trade B: 30 * (180-200) = -600
        a = loaded[trade_a.trade_id]
        b = loaded[trade_b.trade_id]
        assert a.realized_pnl == 750.0, f"a: expected 750, got {a.realized_pnl}"
        assert b.realized_pnl == -600.0, f"b: expected -600, got {b.realized_pnl}"
        # Total should match broker's cumulative
        margins = pc.get_margins()
        # 750 + (-600) = 150
        assert abs(margins["realized_pnl"] - 150.0) < 0.5, \
            f"broker realized_pnl {margins['realized_pnl']} != trade sum 150"
        print(f"  PASS: 2-trade square_off: A=+{a.realized_pnl}, B={b.realized_pnl}, total={margins['realized_pnl']}")


if __name__ == "__main__":
    tests = [
        test_single_leg_buy_profit,
        test_single_leg_buy_loss,
        test_iron_condor_4leg,
        test_sell_leg_profit,
        test_backfill_repairs_zero_pnl,
        test_square_off_all_multi_trade,
    ]
    failed = 0
    for t in tests:
        print(f"\n{t.__name__}:")
        try:
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
