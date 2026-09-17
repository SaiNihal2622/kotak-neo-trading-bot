"""FIX 2026-09-17: tests for orphan position registration.

When paper_client has filled qty positions that aren't tracked by any
ManagedTrade in order_mgr, the reconcile loop flags them as broker_only
and the LLM brain can't manage them. OrderManager.register_orphan_positions
must register each as a managed trade so the brain sees them.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

from kotak_bot.execution.order_manager import OrderManager


class _FakePosition:
    """Minimal stand-in for kotak_bot.broker.paper_client.Position."""
    def __init__(self, symbol, qty, avg_price, underlying='', strike=0, opt_type='', expiry='', exchange='NFO', ltp=0):
        self.symbol = symbol
        self.qty = qty
        self.avg_price = avg_price
        self.ltp = ltp
        self.underlying = underlying
        self.strike = strike
        self.option_type = opt_type
        self.expiry = expiry
        self.exchange = exchange


class _FakeBroker:
    """Minimal stand-in for broker — only get_positions is called by reconcile."""
    def get_positions(self):
        return self._positions

    def set_positions(self, positions):
        self._positions = positions

    def connect(self):
        pass


def _make_om(tmp_path: Path) -> OrderManager:
    """Construct an OrderManager backed by a tmp_path trades_state.json."""
    om = OrderManager.__new__(OrderManager)
    om.broker = _FakeBroker()
    om.smart_router = False
    om.persist_path = tmp_path / "trades_state.json"
    om.persist_path.parent.mkdir(parents=True, exist_ok=True)
    om._lock = __import__('threading').RLock()
    om._trades = {}
    om._symbol_to_trade = {}
    om._on_trade_event = None
    om.resilient = None
    return om


def test_orphan_registers_all_broker_positions(tmp_path):
    om = _make_om(tmp_path)
    broker_pos = [
        _FakePosition("NIFTY17SEP2623200CE", 75, 154.53, "NIFTY", 23200, "CE", "2026-09-17"),
        _FakePosition("NIFTY17SEP2623500CE", 75, 43.78, "NIFTY", 23500, "CE", "2026-09-17"),
        _FakePosition("BANKNIFTY17SEP2656600CE", 30, 627.21, "BANKNIFTY", 56600, "CE", "2026-09-17"),
        _FakePosition("BANKNIFTY17SEP2656800CE", -30, 517.58, "BANKNIFTY", 56800, "CE", "2026-09-17"),
    ]
    n = om.register_orphan_positions(broker_pos)
    assert n == 4, f"expected 4 orphans registered, got {n}"
    assert len(om.open_trades()) == 4
    # Each registered trade has a plan with reason starting with orphan_recovered
    for trade in om.open_trades():
        assert trade.plan.reason.startswith("orphan_recovered_at_startup")
        assert len(trade.orders) == 1


def test_orphan_idempotent_on_second_run(tmp_path):
    """Running orphan-recovery twice does NOT double-register."""
    om = _make_om(tmp_path)
    broker_pos = [
        _FakePosition("NIFTY17SEP2623200CE", 75, 154.53, "NIFTY", 23200, "CE", "2026-09-17"),
        _FakePosition("NIFTY17SEP2623500CE", 75, 43.78, "NIFTY", 23500, "CE", "2026-09-17"),
    ]
    n1 = om.register_orphan_positions(broker_pos)
    assert n1 == 2
    n2 = om.register_orphan_positions(broker_pos)
    assert n2 == 0, f"second run should be no-op, got {n2}"
    assert len(om.open_trades()) == 2


def test_orphan_skips_zero_qty(tmp_path):
    om = _make_om(tmp_path)
    broker_pos = [
        _FakePosition("NIFTY17SEP2623200CE", 75, 154.53, "NIFTY", 23200, "CE", "2026-09-17"),
        _FakePosition("NIFTY17SEP2623500CE", 0, 0, "NIFTY", 23500, "CE", "2026-09-17"),  # ghost
    ]
    n = om.register_orphan_positions(broker_pos)
    assert n == 1
    assert len(om.open_trades()) == 1


def test_orphan_negative_qty_short(tmp_path):
    """Short positions (negative qty) get SELL-side legs."""
    om = _make_om(tmp_path)
    broker_pos = [
        _FakePosition("BANKNIFTY17SEP2656800CE", -30, 517.58, "BANKNIFTY", 56800, "CE", "2026-09-17"),
    ]
    n = om.register_orphan_positions(broker_pos)
    assert n == 1
    trade = om.open_trades()[0]
    assert trade.orders[0].side.value == "SELL"
    assert trade.orders[0].qty == 30