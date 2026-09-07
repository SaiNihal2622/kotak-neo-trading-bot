"""Regression test for orphan-auto-close using real option chain price.

Background (2026-09-07 22:15 IST):
  The orphan-auto-close code path in __main__.py (line ~2065) used to construct
  an Order with only `symbol=...` set, leaving strike/option_type/underlying
  as their dataclass defaults (0.0 / None / None). The paper client's
  _force_fill_market_like had no way to look up the strike in option_chains.json
  (step 0 needed `int(order.strike)` and `order.option_type`) and had no
  underlying for the strike-aware intrinsic fallback (step 4). Result: 3 fills
  today (12:04 BNF 57200/56800 PE, 12:42 NIFTY 24100 PE) all closed for Rs.1.00
  instead of the real ~Rs.245 / ~Rs.307.

  The fix has 3 layers:
  1. The orphan-auto-close code now passes strike/option_type/expiry/underlying
     to Order() (parsed from the position object, or as last-resort from the
     symbol via _parse_option_symbol).
  2. _force_fill_market_like defensively parses strike/option_type/underlying
     from the order's symbol when the Order object didn't carry them.
  3. After fill, _force_fill_market_like backfills strike/option_type/underlying
     onto the Order so downstream Position() creation also has them.

These tests verify the behavior of (2) and (3): that a real option chain price
is used, and that the Order object is backfilled.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from kotak_bot.broker.paper_client import PaperClient
from kotak_bot.broker.base import (
    Order, OrderSide, OrderType, ProductType, OrderStatus, Tick
)


def _write_chain(dcache: Path, underlying: str, spot: float, strike_prices: dict):
    """Write a minimal option_chain_*.json. strike_prices is a dict
    like {"57200_PE": 392.35, "56800_PE": 245.76, ...}."""
    strikes = {}
    for key, price in strike_prices.items():
        strike_i, opt = key.rsplit("_", 1)
        strikes[key] = {
            "strike": int(strike_i),
            "opt_type": opt,
            "price": price,
            "delta": 0.0,
            "gamma": 0.0,
            "vega": 0.0,
            "theta": 0.0,
            "iv": 0.16,
        }
    payload = {
        "spot": spot,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "strikes": strikes,
    }
    out = dcache / f"option_chain_{underlying}.json"
    out.write_text(json.dumps(payload), encoding="utf-8")
    return out


def test_force_fill_parses_strike_from_symbol(tmp_path):
    """When Order has no strike/option_type, _force_fill_market_like should
    parse them from the symbol and use the option_chain price (not Rs.1.00)."""
    dcache = tmp_path / "data_cache"
    dcache.mkdir()
    # Realistic option chain: NIFTY 24300 PE at Rs.548.32, 24100 PE at Rs.307.73.
    _write_chain(dcache, "NIFTY", 23897.7, {
        "24300_PE": 548.32,
        "24100_PE": 307.73,
    })
    persist = dcache / "paper_state.json"
    pc = PaperClient(starting_capital=200000, fill_mode="market_like", persist_path=str(persist))
    # Patch data_cache path lookup: the code uses Path("data_cache"), so we need
    # the working dir to be tmp_path. Use chdir to make the relative path work.
    import os
    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        pc.connect()
        # Simulate the bug: order with no strike/option_type/underlying, just symbol.
        o = Order(
            symbol="NIFTY10SEP2624100PE",
            side=OrderSide.BUY,
            qty=75,
            order_type=OrderType.MARKET,
            product=ProductType.MIS,
            price=0.0,
            tag="ORPHAN-AUTO-CLOSE-TEST",
        )
        assert o.strike == 0.0  # confirms the bug-state
        assert o.option_type is None
        assert o.underlying is None
        placed = pc.place_order(o)
        # Must be COMPLETE (no Rs.1.00 fallback).
        assert placed.status == OrderStatus.COMPLETE
        # Must use the chain price ~307.73, NOT Rs.1.00.
        assert placed.avg_fill_price > 100.0, (
            f"fill fell to fallback Rs.1.00; got {placed.avg_fill_price}"
        )
        assert 305.0 <= placed.avg_fill_price <= 310.0, (
            f"unexpected fill price {placed.avg_fill_price}, expected ~307.73"
        )
        # FIX (3): Order should be backfilled with strike/option_type/underlying
        # so the resulting Position() carries them.
        assert placed.strike == 24100, f"order.strike not backfilled: {placed.strike}"
        assert placed.option_type == "PE"
        assert placed.underlying == "NIFTY"
    finally:
        os.chdir(old_cwd)


def test_force_fill_bnf_orphan_uses_chain_price(tmp_path):
    """BNF 57200 PE orphan-close at 12:04 today got Rs.1.00. After the fix
    it should get the chain price ~392.35."""
    dcache = tmp_path / "data_cache"
    dcache.mkdir()
    _write_chain(dcache, "BANKNIFTY", 57369.65, {
        "57200_PE": 392.35,
        "56800_PE": 245.76,
    })
    persist = dcache / "paper_state.json"
    pc = PaperClient(starting_capital=200000, fill_mode="market_like", persist_path=str(persist))
    import os
    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        pc.connect()
        # SELL 30 BNF 57200 PE (orphan-close of a long position)
        o = Order(
            symbol="BANKNIFTY10SEP2657200PE",
            side=OrderSide.SELL,
            qty=30,
            order_type=OrderType.MARKET,
            product=ProductType.MIS,
            price=0.0,
            tag="ORPHAN-AUTO-CLOSE-TEST",
        )
        placed = pc.place_order(o)
        assert placed.status == OrderStatus.COMPLETE
        assert placed.avg_fill_price > 100.0, (
            f"BNF 57200 PE fill fell to Rs.1.00; got {placed.avg_fill_price}"
        )
        assert 390.0 <= placed.avg_fill_price <= 395.0, (
            f"unexpected fill price {placed.avg_fill_price}, expected ~392.35"
        )
        assert placed.strike == 57200
        assert placed.option_type == "PE"
        assert placed.underlying == "BANKNIFTY"
    finally:
        os.chdir(old_cwd)


def test_force_fill_with_explicit_strike_uses_chain_price(tmp_path):
    """When the Order DOES carry strike/option_type/underlying (the new
    orphan-auto-close path), step 0 still works (uses chain price)."""
    dcache = tmp_path / "data_cache"
    dcache.mkdir()
    _write_chain(dcache, "NIFTY", 23897.7, {
        "24300_PE": 548.32,
    })
    persist = dcache / "paper_state.json"
    pc = PaperClient(starting_capital=200000, fill_mode="market_like", persist_path=str(persist))
    import os
    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        pc.connect()
        # Order WITH strike/option_type/underlying (the new path)
        o = Order(
            symbol="NIFTY10SEP2624300PE",
            side=OrderSide.SELL,
            qty=75,
            order_type=OrderType.MARKET,
            product=ProductType.MIS,
            price=0.0,
            tag="ORPHAN-AUTO-CLOSE-TEST",
            strike=24300,
            option_type="PE",
            expiry="2026-09-10",
            underlying="NIFTY",
        )
        placed = pc.place_order(o)
        assert placed.status == OrderStatus.COMPLETE
        assert 545.0 <= placed.avg_fill_price <= 551.0
    finally:
        os.chdir(old_cwd)


def test_parse_option_symbol_module_helper():
    """kotak_bot.__main__._parse_option_symbol should recover the option
    fields from the symbol string."""
    from kotak_bot.__main__ import _parse_option_symbol
    u, e, s, o = _parse_option_symbol("NIFTY10SEP2624300PE")
    assert u == "NIFTY"
    assert e == "2026-09-10"
    assert s == 24300
    assert o == "PE"
    u, e, s, o = _parse_option_symbol("BANKNIFTY28AUG2657200CE")
    assert u == "BANKNIFTY"
    assert e == "2026-08-28"
    assert s == 57200
    assert o == "CE"
    # Invalid / non-option symbols
    assert _parse_option_symbol("NIFTY") == (None, None, 0, None)
    assert _parse_option_symbol("") == (None, None, 0, None)
    assert _parse_option_symbol(None) == (None, None, 0, None)
    assert _parse_option_symbol("BANKNIFTY-SEP-57200-PE") == (None, None, 0, None)
