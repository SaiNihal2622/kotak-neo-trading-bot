"""Tests for ManagedTrade derived fields and order_manager save/load round-trip."""
from __future__ import annotations

import json
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from kotak_bot.broker.base import (
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    ProductType,
)
from kotak_bot.execution.order_manager import ManagedTrade, OrderManager
from kotak_bot.strategy.base import StrategyName, TradePlan


def _make_order(sym: str, side: OrderSide, qty: int, price: float = 0.0,
                avg_fill: float = 0.0, status: OrderStatus = OrderStatus.OPEN) -> Order:
    return Order(
        order_id=f"O-{sym}",
        symbol=sym,
        side=side,
        qty=qty,
        filled_qty=qty if status == OrderStatus.COMPLETE else 0,
        price=price,
        avg_fill_price=avg_fill,
        order_type=OrderType.LIMIT,
        product=ProductType.MIS,
        status=status,
        placed_at=datetime.now(),
    )


def _make_plan(underlying: str = "NIFTY", strategy: StrategyName = StrategyName.IRON_CONDOR) -> TradePlan:
    return TradePlan(
        strategy=strategy,
        underlying=underlying,
        legs=[
            {"side": "SELL", "qty": 1, "strike": 24450, "opt_type": "CE", "order_type": "LIMIT", "price": 100.0},
            {"side": "BUY", "qty": 1, "strike": 24550, "opt_type": "CE", "order_type": "LIMIT", "price": 50.0},
            {"side": "SELL", "qty": 1, "strike": 24250, "opt_type": "PE", "order_type": "LIMIT", "price": 80.0},
            {"side": "BUY", "qty": 1, "strike": 24150, "opt_type": "PE", "order_type": "LIMIT", "price": 40.0},
        ],
        target=100.0,
        stop=50.0,
        confidence=0.6,
        reason="test",
        expiry="2026-08-12",
        expected_hold_minutes=120,
    )


def test_refresh_derived_open_trade():
    t = ManagedTrade(
        trade_id="T-OPEN",
        plan=_make_plan("NIFTY"),
        orders=[_make_order("NIFTY12AUG2624450CE", OrderSide.SELL, 65, 109.4, 109.4, OrderStatus.COMPLETE)],
        opened_at=datetime(2026, 8, 13, 9, 30, 0),
    )
    OrderManager._refresh_derived(t)
    assert t.status == "open"
    assert t.underlying == "NIFTY"
    assert t.leg_count == 1
    assert t.entry_time == datetime(2026, 8, 13, 9, 30, 0)
    assert t.pnl == 0.0  # no realized P&L yet


def test_refresh_derived_closed_trade():
    t = ManagedTrade(
        trade_id="T-CLOSED",
        plan=_make_plan("BANKNIFTY"),
        orders=[_make_order("BN", OrderSide.BUY, 30, 50.0, 50.0, OrderStatus.COMPLETE)],
        opened_at=datetime(2026, 8, 13, 9, 30, 0),
        closed_at=datetime(2026, 8, 13, 15, 15, 0),
        realized_pnl=275.50,
    )
    OrderManager._refresh_derived(t)
    assert t.status == "closed"
    assert t.underlying == "BANKNIFTY"
    assert t.leg_count == 1
    assert t.pnl == 275.50


def test_refresh_derived_underlying_fallback():
    """If plan is None, underlying defaults to empty string."""
    t = ManagedTrade(
        trade_id="T-NOPLAN",
        plan=None,
        orders=[],
    )
    OrderManager._refresh_derived(t)
    assert t.status == "open"  # closed_at is None by default
    assert t.underlying == ""
    assert t.leg_count == 0


def test_save_state_includes_derived_fields(tmp_path: Path):
    """After save, the file should contain status, underlying, leg_count, pnl, entry_time."""
    broker = MagicMock()
    persist = tmp_path / "trades.json"
    om = OrderManager(broker, persist_path=str(persist))
    # Manually inject a trade
    t = ManagedTrade(
        trade_id="T-TEST",
        plan=_make_plan("NIFTY"),
        orders=[_make_order("NIFTY12AUG2624450CE", OrderSide.SELL, 65, 109.4, 109.4, OrderStatus.COMPLETE)],
        opened_at=datetime(2026, 8, 13, 9, 30, 0),
    )
    om._trades["T-TEST"] = t
    om._symbol_to_trade["NIFTY12AUG2624450CE"] = "T-TEST"
    om._save_state()
    data = json.loads(persist.read_text(encoding="utf-8"))
    saved = data["trades"]["T-TEST"]
    for field in ("status", "underlying", "leg_count", "pnl", "entry_time"):
        assert field in saved, f"missing {field} in saved trade: {saved.keys()}"
    assert saved["status"] == "open"
    assert saved["underlying"] == "NIFTY"
    assert saved["leg_count"] == 1
    assert saved["entry_time"] == "2026-08-13T09:30:00"


def test_load_state_round_trip(tmp_path: Path):
    """After save + reload, the derived fields should be restored."""
    broker = MagicMock()
    persist = tmp_path / "trades.json"
    om1 = OrderManager(broker, persist_path=str(persist))
    t = ManagedTrade(
        trade_id="T-ROUND",
        plan=_make_plan("BANKNIFTY"),
        orders=[
            _make_order("BANKNIFTY12AUG2657700CE", OrderSide.SELL, 30, 566.5, 566.5, OrderStatus.COMPLETE),
            _make_order("BANKNIFTY12AUG2657800CE", OrderSide.BUY, 30, 512.2, 512.2, OrderStatus.COMPLETE),
        ],
        opened_at=datetime(2026, 8, 13, 9, 30, 0),
    )
    om1._trades["T-ROUND"] = t
    om1._save_state()
    # New manager loads from same file
    om2 = OrderManager(broker, persist_path=str(persist))
    loaded = om2._trades.get("T-ROUND")
    assert loaded is not None
    assert loaded.status == "open"
    assert loaded.underlying == "BANKNIFTY"
    assert loaded.leg_count == 2
    assert loaded.entry_time == datetime(2026, 8, 13, 9, 30, 0)
    # And open_trades() must return it
    open_trades = om2.open_trades()
    assert len(open_trades) == 1
    assert open_trades[0].trade_id == "T-ROUND"


def test_load_state_legacy_schema_no_derived_fields(tmp_path: Path):
    """A trades_state.json WITHOUT the new derived fields should still load
    (we fall back to deriving from closed_at + plan)."""
    broker = MagicMock()
    persist = tmp_path / "legacy.json"
    legacy = {
        "trades": {
            "T-LEGACY": {
                "trade_id": "T-LEGACY",
                "plan": {
                    "strategy": "iron_condor",
                    "underlying": "NIFTY",
                    "legs": [],
                    "target": 0.0, "stop": 0.0, "confidence": 0.0,
                    "reason": "", "expiry": "", "expected_hold_minutes": 60,
                },
                "orders": [
                    {"symbol": "NIFTY12AUG2624450CE", "side": "SELL", "qty": 65,
                     "price": 109.4, "avg_fill_price": 109.4, "order_type": "LIMIT",
                     "product": "MIS", "status": "complete", "placed_at": "2026-08-13T09:30:00"}
                ],
                "opened_at": "2026-08-13T09:30:00",
                # NO closed_at (open)
                # NO derived fields (legacy)
            }
        },
        "symbol_to_trade": {"NIFTY12AUG2624450CE": "T-LEGACY"},
    }
    persist.write_text(json.dumps(legacy), encoding="utf-8")
    om = OrderManager(broker, persist_path=str(persist))
    loaded = om._trades["T-LEGACY"]
    assert loaded.status == "open"  # derived from closed_at being absent
    assert loaded.underlying == "NIFTY"  # derived from plan
    assert loaded.leg_count == 1
    assert loaded.entry_time == datetime(2026, 8, 13, 9, 30, 0)


def test_load_state_legacy_schema_closed_trade(tmp_path: Path):
    """Legacy closed trade (has closed_at, no derived fields) should be marked closed."""
    broker = MagicMock()
    persist = tmp_path / "legacy_closed.json"
    legacy = {
        "trades": {
            "T-OLD": {
                "trade_id": "T-OLD",
                "plan": None,
                "orders": [],
                "opened_at": "2026-08-10T09:30:00",
                "closed_at": "2026-08-10T15:15:00",
            }
        },
        "symbol_to_trade": {},
    }
    persist.write_text(json.dumps(legacy), encoding="utf-8")
    om = OrderManager(broker, persist_path=str(persist))
    loaded = om._trades["T-OLD"]
    assert loaded.status == "closed"
    assert loaded.underlying == ""  # no plan
    assert loaded.entry_time == datetime(2026, 8, 10, 9, 30, 0)


def test_open_trades_filters_closed(tmp_path: Path):
    broker = MagicMock()
    persist = tmp_path / "trades.json"
    om = OrderManager(broker, persist_path=str(persist))
    om._trades["T-OPEN"] = ManagedTrade(
        trade_id="T-OPEN", plan=_make_plan("NIFTY"),
        orders=[_make_order("NIFTY1", OrderSide.SELL, 65, 0, 100, OrderStatus.COMPLETE)],
        opened_at=datetime.now(),
    )
    om._trades["T-CLOSED"] = ManagedTrade(
        trade_id="T-CLOSED", plan=_make_plan("BANKNIFTY"),
        orders=[_make_order("BN1", OrderSide.BUY, 30, 0, 50, OrderStatus.COMPLETE)],
        opened_at=datetime.now(),
        closed_at=datetime.now(),
    )
    open_trades = om.open_trades()
    assert len(open_trades) == 1
    assert open_trades[0].trade_id == "T-OPEN"
