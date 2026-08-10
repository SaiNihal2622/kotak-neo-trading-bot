"""Unit tests for OrderManager trade persistence (added 2026-08-10).

Bug context: OrderManager._trades was in-memory only. Every bot restart
(08:33 -> 12:52 -> 13:06 -> 13:55 -> 14:56 today) lost the trade book, so
the EOD square-off at 15:15 only saw 2 of the 6 expected trades and missed
4 naked shorts.

Fix: OrderManager now writes its _trades dict to data_cache/trades_state.json
on every open/close event and reloads on construction.
"""
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kotak_bot.broker.paper_client import PaperClient
from kotak_bot.broker.base import (
    Order, OrderSide, OrderType, ProductType, Tick,
)
from kotak_bot.execution.order_manager import OrderManager
from kotak_bot.strategy.base import TradePlan, StrategyName


def _make_client(tmpdir: str) -> PaperClient:
    pc = PaperClient(
        starting_capital=100_000.0,
        slippage_bps=0.0,
        persist_path=str(Path(tmpdir) / "state.json"),
    )
    pc.connect()
    return pc


def _inject_tick(pc: PaperClient, symbol: str, ltp: float) -> None:
    pc.inject_tick(Tick(
        symbol=symbol, exchange="NFO", ltp=ltp, bid=ltp - 0.05, ask=ltp + 0.05,
        volume=0, timestamp=datetime.utcnow(), underlying="NIFTY",
    ))


def _make_plan(symbol: str, side: str, strike: int, opt_type: str, price: float) -> TradePlan:
    return TradePlan(
        strategy=StrategyName.DIRECTIONAL_DEBIT,
        underlying="NIFTY",
        legs=[{"side": side, "strike": strike, "opt_type": opt_type,
               "qty": 1, "order_type": "MARKET", "price": price,
               "tag": "test"}],
        target=price * 1.5,
        stop=price * 0.5,
        confidence=0.8,
        reason="test",
    )


def test_persist_open_trade():
    """Open trade in instance A should be visible in instance B after restart."""
    with tempfile.TemporaryDirectory() as tmp:
        pc = _make_client(tmp)
        _inject_tick(pc, "NIFTY10AUG2625000CE", 100.0)
        # instance A: open a trade
        mgr_a = OrderManager(pc, persist_path=str(Path(tmp) / "trades.json"))
        plan = _make_plan("NIFTY10AUG2625000CE", "BUY", 25000, "CE", 100.0)
        trade = mgr_a.execute_plan(plan, qty=1, expiry="2026-08-10",
                                    lot_sizes={"NIFTY": 75}, use_bracket=False)
        assert trade.trade_id
        assert trade.opened_at is not None
        # instance B: simulate restart
        mgr_b = OrderManager(pc, persist_path=str(Path(tmp) / "trades.json"))
        loaded = mgr_b.open_trades()
        assert len(loaded) == 1, f"expected 1 open trade after restart, got {len(loaded)}"
        assert loaded[0].trade_id == trade.trade_id
        assert len(loaded[0].orders) == 1
        print(f"  PASS: trade {trade.trade_id} survived simulated restart")


def test_persist_closed_trade():
    """Closed trades should also survive restart (with closed_at set)."""
    with tempfile.TemporaryDirectory() as tmp:
        pc = _make_client(tmp)
        _inject_tick(pc, "NIFTY10AUG2625000CE", 100.0)
        mgr_a = OrderManager(pc, persist_path=str(Path(tmp) / "trades.json"))
        plan = _make_plan("NIFTY10AUG2625000CE", "BUY", 25000, "CE", 100.0)
        trade = mgr_a.execute_plan(plan, qty=1, expiry="2026-08-10",
                                    lot_sizes={"NIFTY": 75}, use_bracket=False)
        mgr_a.close_trade(trade.trade_id, reason="test")
        # restart
        mgr_b = OrderManager(pc, persist_path=str(Path(tmp) / "trades.json"))
        all_trades = list(mgr_b._trades.values())
        assert len(all_trades) == 1
        assert all_trades[0].closed_at is not None
        assert all_trades[0].exit_reason == "test"
        assert len(mgr_b.open_trades()) == 0
        print(f"  PASS: closed trade {trade.trade_id} survived restart with closed_at preserved")


def test_persist_multi_leg():
    """Multi-leg iron condor: all 4 orders should be tracked under 1 trade_id."""
    with tempfile.TemporaryDirectory() as tmp:
        pc = _make_client(tmp)
        # inject ticks for all 4 legs
        for sym, ltp in [
            ("NIFTY10AUG2624600CE", 60.0),
            ("NIFTY10AUG2624700CE", 40.0),
            ("NIFTY10AUG2624400PE", 50.0),
            ("NIFTY10AUG2624300PE", 35.0),
        ]:
            _inject_tick(pc, sym, ltp)
        mgr_a = OrderManager(pc, persist_path=str(Path(tmp) / "trades.json"))
        from kotak_bot.strategy.base import TradePlan
        plan = TradePlan(
            strategy=StrategyName.IRON_CONDOR,
            underlying="NIFTY",
            legs=[
                {"side": "SELL", "strike": 24600, "opt_type": "CE", "qty": 1,
                 "order_type": "MARKET", "price": 60.0, "tag": "ic_NIFTY_sc"},
                {"side": "BUY",  "strike": 24700, "opt_type": "CE", "qty": 1,
                 "order_type": "MARKET", "price": 40.0, "tag": "ic_NIFTY_lc"},
                {"side": "SELL", "strike": 24400, "opt_type": "PE", "qty": 1,
                 "order_type": "MARKET", "price": 50.0, "tag": "ic_NIFTY_sp"},
                {"side": "BUY",  "strike": 24300, "opt_type": "PE", "qty": 1,
                 "order_type": "MARKET", "price": 35.0, "tag": "ic_NIFTY_lp"},
            ],
            target=30.0,
            stop=300.0,
            confidence=0.7,
            reason="test iron condor",
        )
        trade = mgr_a.execute_plan(plan, qty=1, expiry="2026-08-10",
                                    lot_sizes={"NIFTY": 75}, use_bracket=False)
        assert len(trade.orders) == 4, f"expected 4 legs, got {len(trade.orders)}"
        # restart and verify all 4 legs persist
        mgr_b = OrderManager(pc, persist_path=str(Path(tmp) / "trades.json"))
        loaded = mgr_b.open_trades()
        assert len(loaded) == 1
        assert len(loaded[0].orders) == 4, f"expected 4 legs after restart, got {len(loaded[0].orders)}"
        # symbol_to_trade lookup should also work
        tid = mgr_b._symbol_to_trade.get("NIFTY10AUG2624600CE")
        assert tid == trade.trade_id
        print(f"  PASS: 4-leg iron condor persisted with all legs ({trade.trade_id})")


if __name__ == "__main__":
    tests = [
        test_persist_open_trade,
        test_persist_closed_trade,
        test_persist_multi_leg,
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
