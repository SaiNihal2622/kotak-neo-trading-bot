"""Tests for the ADX (Average Directional Index) indicator in candle_engine.

ADX is a trend-strength indicator (NOT direction). Used by nifty_cash_long/short
strategies in strategy_library: ADX > 25 = trending regime.

Wilder's smoothing (different from EMA):
- first value = sum of first N values / N
- subsequent = (prev * (N-1) + current) / N
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _make_bars(prices, start_hour=9, start_minute=15):
    """Build OHLCV bars from a price list."""
    bars = []
    for i, p in enumerate(prices):
        minute = start_minute + i
        h_offset = minute // 60
        actual_hour = start_hour + h_offset
        actual_minute = minute % 60
        bars.append({
            'ts': f'2026-09-29T{actual_hour:02d}:{actual_minute:02d}:00',
            'o': p - 0.5,
            'h': p + 1,
            'l': p - 1,
            'c': p,
            'v': 1000,
        })
    return bars


class TestADXCalculation:
    """ADX (Average Directional Index) returns trend strength 0-100."""

    def test_strict_uptrend_adx_near_100(self):
        """Constant +5/bar trend should give ADX ≈ 100 (max trend strength)."""
        from scripts.candle_engine import CandleEngine
        uptrend = [22000 + i * 5 for i in range(60)]
        bars = _make_bars(uptrend)
        adx = CandleEngine._adx(bars, 14)
        assert adx is not None
        assert adx >= 95, f"Strict uptrend should give ADX ≈ 100, got {adx}"

    def test_strict_downtrend_adx_near_100(self):
        """Constant -5/bar trend should give ADX ≈ 100 (max trend strength)."""
        from scripts.candle_engine import CandleEngine
        downtrend = [22800 - i * 5 for i in range(60)]
        bars = _make_bars(downtrend)
        adx = CandleEngine._adx(bars, 14)
        assert adx is not None
        assert adx >= 95, f"Strict downtrend should give ADX ≈ 100, got {adx}"

    def test_sideways_adx_below_25(self):
        """Pure sideways noise should give ADX < 25 (ranging, no trend)."""
        import random
        random.seed(42)
        from scripts.candle_engine import CandleEngine
        sideways = [22500 + random.randint(-10, 10) for _ in range(60)]
        bars = _make_bars(sideways)
        adx = CandleEngine._adx(bars, 14)
        assert adx is not None
        assert adx < 25, f"Sideways should give ADX < 25, got {adx}"

    def test_insufficient_data_returns_none(self):
        """Need at least 2*N+1 bars to compute ADX."""
        from scripts.candle_engine import CandleEngine
        bars = _make_bars([22500 + i for i in range(10)])  # too few
        adx = CandleEngine._adx(bars, 14)
        assert adx is None


class TestADXInComputeIndicators:
    """ADX must be exposed in compute_indicators so it lands in candles_aggregate.json."""

    def test_compute_indicators_returns_adx_field(self):
        """compute_indicators must include 'adx' key in the output dict."""
        from scripts.candle_engine import CandleEngine
        eng = CandleEngine()
        sym = 'NIFTY'
        uptrend = [22000 + i * 5 for i in range(60)]
        eng.bars[sym]['1m'] = _make_bars(uptrend)
        eng.last_ltp[sym] = uptrend[-1]
        inds = eng.compute_indicators(sym, '1m')
        assert 'adx' in inds, "compute_indicators must include 'adx'"
        assert inds['adx'] is not None
        assert inds['adx'] >= 95  # trending data

    def test_sideways_compute_indicators_adx_below_25(self):
        """Sideways data should produce ADX < 25 from compute_indicators."""
        import random
        random.seed(7)
        from scripts.candle_engine import CandleEngine
        eng = CandleEngine()
        sym = 'NIFTY'
        sideways = [22500 + random.randint(-10, 10) for _ in range(60)]
        eng.bars[sym]['1m'] = _make_bars(sideways)
        eng.last_ltp[sym] = sideways[-1]
        inds = eng.compute_indicators(sym, '1m')
        assert inds['adx'] < 25, (
            f"Sideways ADX should be <25, got {inds['adx']} — "
            "strategy_library CAS would never trigger when ADX is wrong"
        )