"""Tests for the regime-routing backtest harness (2026-10-13)."""

import sys
from pathlib import Path

import pytest

ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
sys.path.insert(0, str(ROOT / 'scripts'))
import backtest_routing as BR


def test_load_bars():
    bars = BR._load_bars()
    assert len(bars) > 50
    r = bars[0]
    assert 'date' in r and 'open' in r and 'close' in r


def test_classify():
    assert BR._classify(0.1) == 'range'
    assert BR._classify(0.6) == 'mild'
    assert BR._classify(1.5) == 'trend'


def test_regime_from_day():
    base = [{'close': 100.0 + i * 2} for i in range(16)]  # steady up-trend
    bar = {'open': 100.0}
    adx, sess = BR._regime_from_day(base, bar)
    assert adx > 50  # strongly directional
    assert isinstance(sess, float)


def test_run_routed_returns_summary():
    s = BR.run(use_routing=True)
    assert 'total_pnl' in s
    assert s['n_days'] > 100
    assert 'picks' in s
    # routing must NOT be 100% iron_condor (it fires trend strategies)
    assert s['picks'].get('iron_condor_nifty', 0) < s['n_days']


def test_routing_beats_iron_condor_only_on_trends():
    """The whole point: routed trend-day P&L must beat the template's."""
    sys.path.insert(0, str(ROOT / 'scripts'))
    import importlib
    m = importlib.import_module('backtest_routing')
    importlib.reload(m)
    off = m.run(use_routing=False)
    importlib.reload(m)
    on = m.run(use_routing=True)
    t_off = (off.get('by_regime', {}) or {}).get('trend', {}).get('pnl', 0)
    t_on = (on.get('by_regime', {}) or {}).get('trend', {}).get('pnl', 0)
    assert t_on > t_off
