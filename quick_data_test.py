"""Test data feed without main loop."""
import sys
sys.path.insert(0, '.')

import loguru
loguru.logger.remove()
loguru.logger.add("data_test.txt", level="INFO")

from kotak_bot.data.historical import HistoricalData
hist = HistoricalData(source="nselib")
df = hist.get_equity_ohlc("NIFTY", days=180)
print(f"NIFTY OHLCV: {len(df)} rows")
if not df.empty:
    print(f"  range: {df['date'].min()} -> {df['date'].max()}")
    print(df.head(3).to_string())
else:
    print("  no data — nselib needs internet, may be blocked")
    print("  falling back to synthetic")

# Try synthetic fallback
import pandas as pd
import numpy as np
np.random.seed(42)
end = pd.Timestamp.now()
dates = pd.bdate_range(end=end, periods=180)
base = 24500
returns = np.random.normal(0.0005, 0.012, size=len(dates))
close = base * (1 + pd.Series(returns)).cumprod()
open_ = close.shift(1).fillna(base)
high = pd.concat([open_, close], axis=1).max(axis=1) * (1 + np.abs(np.random.normal(0, 0.005, size=len(dates))))
low = pd.concat([open_, close], axis=1).min(axis=1) * (1 - np.abs(np.random.normal(0, 0.005, size=len(dates))))
synth = pd.DataFrame({
    "date": dates,
    "open": open_.round(2),
    "high": high.round(2),
    "low": low.round(2),
    "close": close.round(2),
})
print(f"\nSynthetic NIFTY 180d: {len(synth)} rows")
print(synth.head(3).to_string())
