"""Smoke test ADX on synthetic uptrend + downtrend + sideways."""
import sys
sys.path.insert(0, '.')
from scripts.candle_engine import CandleEngine
import json

# Build candles for trending, ranging, downtrending
def make_bars(prices, start_ts='2026-09-29T09:15:00'):
    bars = []
    for i, p in enumerate(prices):
        h = p + 1
        l = p - 1
        o = p - 0.5
        c = p
        v = 1000
        ts = f'2026-09-29T09:{15 + i:02d}:00'
        bars.append({'ts': ts, 'o': o, 'h': h, 'l': l, 'c': c, 'v': v})
    return bars

# Uptrend: 50 bars, +5 each
uptrend = [22000 + i * 5 for i in range(60)]
bars = make_bars(uptrend)
adx = CandleEngine._adx(bars, 14)
print(f"Uptrend ADX (60 bars, +5/bar): {adx:.2f}")

# Sideways: 50 bars of 22500 + noise
import random
random.seed(42)
sideways = [22500 + random.randint(-10, 10) for _ in range(60)]
bars = make_bars(sideways)
adx = CandleEngine._adx(bars, 14)
print(f"Sideways ADX (60 bars, ±10): {adx:.2f}")

# Downtrend: -5 each
downtrend = [22800 - i * 5 for i in range(60)]
bars = make_bars(downtrend)
adx = CandleEngine._adx(bars, 14)
print(f"Downtrend ADX (60 bars, -5/bar): {adx:.2f}")

# Test compute_indicators end-to-end
print()
print("=" * 60)
print("End-to-end compute_indicators test:")
print("=" * 60)

# Insert bars into engine and test
eng = CandleEngine()
# Use _bars dict directly to simulate state
sym = 'NIFTY'
eng.bars[sym]['1m'] = make_bars(uptrend)
eng.last_ltp[sym] = uptrend[-1]

inds = eng.compute_indicators(sym, '1m')
print(f"Indicators for trending NIFTY: {json.dumps(inds, indent=2)}")
print(f"ADX in indicators: {inds.get('adx')}")