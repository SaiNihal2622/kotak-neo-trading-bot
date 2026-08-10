"""Run multiple backtests to find what works on NIFTY.

Strategies:
1. SMA cross + RSI (directional, long premium) — already showed -1.71
2. ADX filter: only trade when ADX < 20 (range-bound)
3. Short strangle in low-ADX, hold 3 days, exit at +50% or -100% of credit
4. Buy on RSI<30 + sell at RSI>50 (mean reversion)
"""
import sys
sys.path.insert(0, '.')

import loguru
loguru.logger.remove()
loguru.logger.add("backtest2_out.txt", level="INFO")

LOG = open("backtest2_out.txt", "w", encoding="utf-8")
def o(m): LOG.write(m + "\n"); LOG.flush()

from kotak_bot.data.historical import HistoricalData
import pandas as pd
import pandas_ta as ta
import numpy as np

hist = HistoricalData()
df = hist.get_equity_ohlc("NIFTY", days=365)  # 1 year
o(f"Data: {len(df)} rows, {df['date'].min().date()} to {df['date'].max().date()}")

if df.empty:
    o("No data"); sys.exit(1)

# indicators
df["ema9"] = ta.ema(df["close"], length=9)
df["ema21"] = ta.ema(df["close"], length=21)
df["rsi14"] = ta.rsi(df["close"], length=14)
df["atr14"] = ta.atr(df["high"], df["low"], df["close"], length=14)
df["adx14"] = ta.adx(df["high"], df["low"], df["close"], length=14)["ADX_14"]
df.dropna(inplace=True)
o(f"After indicators: {len(df)} rows")

def compute_metrics(ret_series, label, trades):
    total = (1 + ret_series).prod() - 1
    n = len(ret_series)
    yrs = max(n / 252, 0.1)
    annual = (1 + total) ** (1 / yrs) - 1
    vol = ret_series.std() * (252 ** 0.5)
    sharpe = (annual - 0.05) / max(vol, 1e-9)
    cum = (1 + ret_series).cumprod()
    dd = (cum / cum.cummax() - 1).min()
    wins = (ret_series > 0).sum()
    losses = (ret_series < 0).sum()
    o(f"\n  {label}")
    o(f"    Trades: {trades}, Total: {total*100:.1f}%, Annual: {annual*100:.1f}%, Sharpe: {sharpe:.2f}, Max DD: {dd*100:.1f}%, Win: {wins/(wins+losses)*100:.0f}% ({wins}W/{losses}L)")
    return sharpe

# ============================================================
# Strategy 1: Short strangle in low-ADX range
# ============================================================
o("=" * 60)
o("STRATEGY 1: Short strangle in low-ADX (range-bound) market")
o("=" * 60)
df["ret"] = df["close"].pct_change()
df["signal"] = 0
df.loc[(df["adx14"] < 20) & (df["rsi14"] > 40) & (df["rsi14"] < 60), "signal"] = -1  # short premium
df.loc[(df["adx14"] > 30) | (df["rsi14"] < 25) | (df["rsi14"] > 75), "signal"] = 1   # cover
df["pos"] = df["signal"].replace(to_replace=0, method="ffill").fillna(0)
df["trade"] = df["pos"].diff().abs()
n_trades = int(df["trade"].sum() / 2)
df["strat1"] = df["pos"].shift(1) * df["ret"] - df["trade"] * 0.0005
compute_metrics(df["strat1"], "Short strangle in range", n_trades)

# ============================================================
# Strategy 2: Mean reversion
# ============================================================
o("\n" + "=" * 60)
o("STRATEGY 2: Mean reversion (RSI<30 buy, RSI>50 sell)")
o("=" * 60)
df["signal2"] = 0
df.loc[df["rsi14"] < 30, "signal2"] = 1
df.loc[df["rsi14"] > 50, "signal2"] = -1
df["pos2"] = df["signal2"].replace(to_replace=0, method="ffill").fillna(0)
df["trade2"] = df["pos2"].diff().abs()
n_trades2 = int(df["trade2"].sum() / 2)
df["strat2"] = df["pos2"].shift(1) * df["ret"] - df["trade2"] * 0.0005
compute_metrics(df["strat2"], "Mean reversion", n_trades2)

# ============================================================
# Strategy 3: Buy only (no short) on trend signals
# ============================================================
o("\n" + "=" * 60)
o("STRATEGY 3: Buy only on confirmed uptrend (EMA + ADX>25)")
o("=" * 60)
df["signal3"] = 0
df.loc[(df["ema9"] > df["ema21"]) & (df["adx14"] > 25), "signal3"] = 1
df["pos3"] = df["signal3"].replace(to_replace=0, method="ffill").fillna(0)
df["trade3"] = df["pos3"].diff().abs()
n_trades3 = int(df["trade3"].sum() / 2)
df["strat3"] = df["pos3"].shift(1) * df["ret"] - df["trade3"] * 0.0005
compute_metrics(df["strat3"], "Buy on uptrend", n_trades3)

# ============================================================
# Strategy 4: Sell in high ADX (trending), buy in low ADX (range)
# ============================================================
o("\n" + "=" * 60)
o("STRATEGY 4: Sell in trending, buy in range (regime-based)")
o("=" * 60)
df["signal4"] = 0
df.loc[df["adx14"] > 25, "signal4"] = -1  # sell in trending (contrarian)
df.loc[df["adx14"] < 20, "signal4"] = 1   # buy in range
df["pos4"] = df["signal4"].replace(to_replace=0, method="ffill").fillna(0)
df["trade4"] = df["pos4"].diff().abs()
n_trades4 = int(df["trade4"].sum() / 2)
df["strat4"] = df["pos4"].shift(1) * df["ret"] - df["trade4"] * 0.0005
compute_metrics(df["strat4"], "Regime contrarian", n_trades4)

# ============================================================
# Strategy 5: Buy & Hold (benchmark)
# ============================================================
o("\n" + "=" * 60)
o("STRATEGY 5: Buy & Hold benchmark")
o("=" * 60)
df["strat5"] = df["ret"]
compute_metrics(df["strat5"], "Buy & Hold NIFTY", 1)

# ============================================================
# Strategy 6: Bollinger Band mean reversion
# ============================================================
o("\n" + "=" * 60)
o("STRATEGY 6: Bollinger Band mean reversion")
o("=" * 60)
bb = ta.bbands(df["close"], length=20, std=2)
df["bbl"] = bb.iloc[:, 0]  # lower band
df["bbm"] = bb.iloc[:, 1]  # middle
df["bbu"] = bb.iloc[:, 2]  # upper
df["signal6"] = 0
df.loc[df["close"] < df["bbl"], "signal6"] = 1
df.loc[df["close"] > df["bbu"], "signal6"] = -1
df["pos6"] = df["signal6"].replace(to_replace=0, method="ffill").fillna(0)
df["trade6"] = df["pos6"].diff().abs()
n_trades6 = int(df["trade6"].sum() / 2)
df["strat6"] = df["pos6"].shift(1) * df["ret"] - df["trade6"] * 0.0005
compute_metrics(df["strat6"], "Bollinger mean reversion", n_trades6)

o("\n" + "=" * 60)
o("SUMMARY")
o("=" * 60)
o("The best strategy (if any has Sharpe > 0.5) is what we should pursue.")
o("If all are negative or near-zero, the regime-based selector (iron condor in range, strangle in range) is the better path.")

LOG.close()
