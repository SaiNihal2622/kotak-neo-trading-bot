"""Tests for the regime-aware strategy routing fix (2026-10-13).

Root cause: select_strategy gave iron_condor a static weight (0.9) that
always beat the trend strategies (0.75/0.70), so even a strong trending day
(ADX 45, session +0.6%) routed to the range-bound iron condor. This was the
biggest source of 'template operating' and missed directional P&L all month.

The fix adds a regime-aware weight adjustment: trending (ADX>25 & |session%|>0.3)
demotes iron_condor and boosts the correct-direction strategy; ranging does
the reverse.
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\scripts')
sys.path.insert(0, str(ROOT))
import strategy_library as SL

DATA = ROOT.parent / 'data_cache'


def _ctx(adx, session_pct, vix=14.0, rsi2_extreme=None):
    """Build a deterministic context. session_pct is in % (e.g. 0.6 = +0.6%)."""
    closes = [22500 + i * 5 for i in range(20)]  # smooth rising closes
    spot = closes[-1]
    session_open = spot / (1 + session_pct / 100)
    # patch candles_aggregate adx for the selector's real-file read
    ca_path = DATA / 'candles_aggregate.json'
    ca = json.loads(ca_path.read_text(encoding='utf-8'))
    ca['symbols']['NIFTY']['indicators']['adx'] = adx
    ca_path.write_text(json.dumps(ca))
    return {
        'spot': spot, 'vix': vix, 'session_open': session_open,
        'candles': [{'o': c - 2, 'h': c + 5, 'l': c - 5, 'c': c, 'v': 100} for c in closes],
        'now': _fake_now(11, 0), 'vwap': spot,
    }


def _fake_now(h, m):
    import datetime
    return datetime.datetime(2026, 10, 13, h, m)


@pytest.fixture(autouse=True)
def _restore_adx():
    yield
    ca_path = DATA / 'candles_aggregate.json'
    ca = json.loads(ca_path.read_text(encoding='utf-8'))
    ca['symbols']['NIFTY']['indicators']['adx'] = 0
    ca_path.write_text(json.dumps(ca))


def test_trending_up_routes_to_cash_long():
    """ADX 45, session +0.6% (a real up-trend day) must NOT pick iron_condor."""
    sel = SL.select_strategy(_ctx(45, +0.6), {})
    assert sel is not None
    assert sel.name in ('nifty_cash_long', 'nifty_cash_short', 'long_call')


def test_trending_up_prefers_cash_long_not_iron_condor():
    """On an up-trend, the winning candidate must not be iron_condor."""
    sel = SL.select_strategy(_ctx(45, +0.6), {})
    assert sel.name != 'iron_condor_nifty'


def test_range_routes_to_iron_condor():
    """ADX 12, session -0.04% (flat) must keep iron_condor (its best case)."""
    sel = SL.select_strategy(_ctx(12, -0.04), {})
    assert sel is not None
    assert sel.name == 'iron_condor_nifty'


def test_mild_up_adx30_routes_to_cash_long():
    sel = SL.select_strategy(_ctx(30, +0.63), {})
    assert sel.name != 'iron_condor_nifty'
    assert sel.name in ('nifty_cash_long', 'long_call', 'vwap_bounce_nifty')


def test_trending_down_avoids_iron_condor():
    sel = SL.select_strategy(_ctx(40, -0.8), {})
    assert sel.name != 'iron_condor_nifty'
