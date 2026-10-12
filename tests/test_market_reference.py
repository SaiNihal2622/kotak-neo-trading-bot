"""Tests for the market reference module (real historical data grounding).

Addresses the gap where strategy-entry gates (e.g. iron_condor 'VIX<15')
were fixed guesses. This module pulls REAL historical India VIX, computes
percentile rank, and grounds the gate decision in market history — a
prior the paper-trade learner can't provide with ~20 samples.

Run:
    .venv\\Scripts\\python.exe -m pytest tests/test_market_reference.py -q
"""

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')


@pytest.fixture()
def mr(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location('mr_ut', ROOT / 'scripts' / 'market_reference.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.DATA = tmp_path
    m.OUT = tmp_path / 'market_reference.json'
    return m


def test_pct_rank_basic(mr):
    assert mr._pct_rank(10, [1, 2, 3, 4, 5]) == 100.0
    assert mr._pct_rank(3, [1, 2, 3, 4, 5]) == 60.0
    assert mr._pct_rank(1, [1, 2, 3, 4, 5]) == 20.0
    assert mr._pct_rank(5, [1, 2, 3, 4, 5]) == 100.0


def test_pct_rank_empty(mr):
    assert mr._pct_rank(10, []) is None


def test_fetch_vix_history_real(mr):
    """With network, should return real India VIX closes (len > 0)."""
    hist = mr.fetch_vix_history(period="1mo")
    assert len(hist) > 0
    assert all(isinstance(x, float) for x in hist)


def test_fetch_vix_history_handles_bad_ticker(mr, monkeypatch):
    """Graceful empty on failure - caller must not crash."""
    def _fake_dl(*a, **k):
        raise RuntimeError("no network")
    monkeypatch.setattr(sys, 'modules', {**sys.modules})
    import importlib
    # stub yfinance to raise
    class _FakeYF:
        def download(self, *a, **k): raise RuntimeError("fail")
    real_import = __import__
    def _could_import(name, *a, **k):
        if name == 'yfinance':
            return _FakeYF()
        return real_import(name, *a, **k)
    monkeypatch.setattr('builtins.__import__', _could_import)
    assert mr.fetch_vix_history() == []


def test_build_writes_file_and_advice(mr, monkeypatch):
    """build() with real data writes the file, sets advice only when grounded."""
    monkeypatch.setattr(mr, 'fetch_vix_history', lambda *a, **k: [10.0, 11.0, 12.0, 14.0, 15.0, 16.0, 16.5])
    result = mr.build()
    assert mr.OUT.exists()
    assert result['vix_history']['n_points'] == 7
    # latest = vix_hist[-1] = 16.5 -> pct rank = 100 (all values <= 16.5)
    assert result['vix_history']['latest'] == pytest.approx(16.5)
    assert result['vix_history']['latest_pct_rank'] == 100.0
    assert result['advice_available'] is True
    assert 'iron_condor_gate_note' in result['regime_features']
    # 16.5 at 100th pct > 50 => elevated note
    assert 'Elevated' in result['regime_features']['iron_condor_gate_note']


def test_build_no_data_no_crash(mr, monkeypatch):
    monkeypatch.setattr(mr, 'fetch_vix_history', lambda *a, **k: [])
    result = mr.build()
    assert result['vix_history']['n_points'] == 0
    assert result['advice_available'] is False
    assert result['regime_features'] == {}
