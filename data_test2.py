"""Quick data test."""
import sys
sys.path.insert(0, '.')

import loguru
loguru.logger.remove()
loguru.logger.add("data_test.txt", level="INFO")

from kotak_bot.data.historical import HistoricalData
hist = HistoricalData()
df = hist.get_equity_ohlc("NIFTY", days=180)
print(f"NIFTY: {len(df)} rows")
if not df.empty:
    print(f"  range: {df['date'].min().date()} -> {df['date'].max().date()}")
    print(f"  cols: {list(df.columns)}")
    print(f"  latest: {df.iloc[-1].to_dict()}")
else:
    print("  empty")
