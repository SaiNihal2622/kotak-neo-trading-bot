"""Run a real backtest on actual NIFTY data (yfinance, 6 months)."""
import sys
sys.path.insert(0, '.')

import loguru
loguru.logger.remove()
loguru.logger.add("backtest_out.txt", level="INFO")

LOG = open("backtest_out.txt", "w", encoding="utf-8")
def o(m): LOG.write(m + "\n"); LOG.flush()

# 1) Get real NIFTY data
from kotak_bot.data.historical import HistoricalData
hist = HistoricalData()
df = hist.get_equity_ohlc("NIFTY", days=180)
o(f"Data: {len(df)} rows, {df['date'].min().date()} to {df['date'].max().date()}")

if df.empty:
    o("No data — exiting")
    sys.exit(1)

# 2) Compute indicators using pandas-ta
import pandas_ta as ta
df["ema9"] = ta.ema(df["close"], length=9)
df["ema21"] = ta.ema(df["close"], length=21)
df["rsi14"] = ta.rsi(df["close"], length=14)
df["atr14"] = ta.atr(df["high"], df["low"], df["close"], length=14)
df["adx14"] = ta.adx(df["high"], df["low"], df["close"], length=14)["ADX_14"]
df.dropna(inplace=True)
o(f"After indicators: {len(df)} rows")

# 3) Define strategy: SMA cross + RSI filter + ADX filter
df["signal"] = 0
# BUY when ema9 crosses above ema21, RSI < 70, ADX > 20 (trending)
df.loc[(df["ema9"] > df["ema21"]) & (df["rsi14"] < 70) & (df["adx14"] > 20), "signal"] = 1
# SELL when ema9 crosses below ema21, RSI > 30, ADX > 20
df.loc[(df["ema9"] < df["ema21"]) & (df["rsi14"] > 30) & (df["adx14"] > 20), "signal"] = -1
df["position"] = df["signal"].replace(to_replace=0, method="ffill").fillna(0)
df["trade"] = df["position"].diff().abs()
n_trades = int(df["trade"].sum() / 2)

# 4) Compute returns
df["ret"] = df["close"].pct_change()
df["strat_ret"] = df["position"].shift(1) * df["ret"]
# brokerage: 0.005% per side
df.loc[df["trade"] > 0, "strat_ret"] -= 0.0005

# 5) Compute metrics
total_ret = (1 + df["strat_ret"]).prod() - 1
n_days = len(df)
n_years = max(n_days / 252, 0.1)
annual_ret = (1 + total_ret) ** (1 / n_years) - 1
vol = df["strat_ret"].std() * (252 ** 0.5)
sharpe = (annual_ret - 0.05) / max(vol, 1e-9)  # assume 5% risk-free
cum = (1 + df["strat_ret"]).cumprod()
peak = cum.cummax()
dd = (cum / peak - 1).min()
# win rate
wins = (df["strat_ret"] > 0).sum()
losses = (df["strat_ret"] < 0).sum()
win_rate = wins / max(wins + losses, 1)

o("")
o("=" * 60)
o(f"BACKTEST RESULT — NIFTY directional, 6 months daily data")
o("=" * 60)
o(f"  Strategy: SMA 9/21 cross + RSI filter + ADX>20 filter")
o(f"  Period: {df['date'].min().date()} → {df['date'].max().date()} ({n_days} days)")
o(f"  Trades: {n_trades}")
o(f"  Total return: {total_ret*100:.1f}%")
o(f"  Annualized: {annual_ret*100:.1f}%")
o(f"  Volatility: {vol*100:.1f}%")
o(f"  Sharpe ratio: {sharpe:.2f}")
o(f"  Max drawdown: {dd*100:.1f}%")
o(f"  Win rate: {win_rate*100:.1f}% ({wins}W / {losses}L)")
o("")
if sharpe > 1.0:
    o("VERDICT: ✅ Good — Sharpe > 1.0, strategy has edge")
elif sharpe > 0:
    o("VERDICT: 🟡 Marginal — Sharpe > 0 but not strong edge")
else:
    o("VERDICT: ❌ Negative — strategy loses money")

LOG.close()
