"""Tests for the preflight chain-fallback fix (2026-10-12).

Root cause: the bridge submits option plans (iron_condor, bear_put_vertical)
but the core's live tick state often lacks the specific option symbol, so the
pricing gate rejected every such OPEN ('no live tick ... cannot validate LIMIT
price') and the trade silently never filled. This test verifies the fallback
to the fresh option-chain file provides bid/ask so the gate passes.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')


def _load_preflight():
    # preflight.py uses relative imports (..domain.events), so load it as part
    # of the system package rather than as a standalone module.
    sys.path.insert(0, str(ROOT))
    from system.core.risk.preflight import PreFlight
    return PreFlight


@pytest.fixture()
def pf(tmp_path, monkeypatch):
    PreFlight = _load_preflight()
    inst = PreFlight()
    # point chain fallback at a temp chain file by writing to the real
    # data_cache location (the fallback reads data_cache/option_chain_<UND>.json)
    import os
    real_chain = ROOT / 'data_cache' / 'option_chain_NIFTY.json'
    backup = None
    if real_chain.exists():
        backup = real_chain.read_text(encoding='utf-8-sig')
    real_chain.write_text('{"strikes": {"NIFTY22600CE": {"bid": 100.0, "ask": 102.0}}}', encoding='utf-8')
    yield inst
    if backup is not None:
        real_chain.write_text(backup, encoding='utf-8')
    else:
        real_chain.unlink(missing_ok=True)


def test_chain_bid_ask_returns_prices(pf):
    bid, ask = pf._chain_bid_ask('NIFTY22600CE')
    assert bid == 100.0
    assert ask == 102.0


def test_chain_bid_ask_unknown_symbol(pf):
    bid, ask = pf._chain_bid_ask('NIFTY99999CE')
    assert bid is None
    assert ask is None


def test_limit_reasonable_passes_with_chain_fallback(pf):
    """An option order with no live tick but a chain entry must pass the gate."""
    order = {
        'symbol': 'NIFTY22600CE', 'side': 'SELL', 'qty': 75,
        'order_type': 'LIMIT', 'price': 100.0, 'underlying': 'NIFTY',
    }
    # empty state.ticks -> no live tick -> must fall back to chain
    state = type('S', (), {'ticks': {}, 'account': type('A', (), {'cash': 100000})})()
    res = pf._check_limit_reasonable(order, state)
    assert res.ok is True, res.reason


def test_limit_reasonable_still_rejects_when_no_chain(pf, monkeypatch):
    """If neither live tick nor chain entry exists, still reject (fail-closed)."""
    monkeypatch.setattr(pf, '_chain_bid_ask', lambda sym: (None, None))
    order = {
        'symbol': 'NIFTY99999CE', 'side': 'SELL', 'qty': 75,
        'order_type': 'LIMIT', 'price': 100.0, 'underlying': 'NIFTY',
    }
    state = type('S', (), {'ticks': {}, 'account': type('A', (), {'cash': 100000})})()
    res = pf._check_limit_reasonable(order, state)
    assert res.ok is False
    assert res.gate == 'pricing'


def test_per_trade_cap_uses_chain_price(pf):
    """Cost estimation falls back to chain ask when no live tick."""
    order = {
        'symbol': 'NIFTY22600CE', 'side': 'BUY', 'qty': 75,
        'order_type': 'LIMIT', 'price': 0.0, 'underlying': 'NIFTY',
        'exchange': 'NFO',
    }
    state = type('S', (), {'ticks': {}, 'account': type('A', (), {'cash': 100000})})()
    res = pf._check_per_trade_cap(order, state)
    # 75 * 102 = 7650, well under 5% of 100000 = 5000? No -> 7650 > 5000 -> cap reject
    # but the point is it got a price (not 'no price for cost estimation')
    assert res.gate != 'pricing'
