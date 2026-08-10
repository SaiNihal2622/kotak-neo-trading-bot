"""Real backtest runner.

Uses Dhan (free) for historical 1-min data + vectorbt for backtesting.
Falls back to synthetic data if Dhan not configured.

Run: python -m kotak_bot.backtest.real_backtest
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, '.')

# silence loguru
import loguru
loguru.logger.remove()
loguru.logger.add("backtest_run.log", level="INFO")

from loguru import logger

from kotak_bot.data.dhan import DhanDataFeed
from kotak_bot.backtest.engine import BacktestEngine


def run_dhan_backtest(underlying: str = "NIFTY", days: int = 180, interval: int = 5) -> int:
    """Run backtest on real Dhan data. Returns Sharpe ratio or 0 on failure."""
    dhan = DhanDataFeed()
    if not dhan.enabled:
        logger.warning("Dhan not enabled. Add DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN to .env to use real data.")
        logger.info("Falling back to synthetic data for demonstration.")
        from kotak_bot.data.historical import HistoricalData
        hist = HistoricalData(source="nselib")
        df = hist.get_equity_ohlc(underlying, days=days)
        if df.empty:
            logger.error("No historical data available — cannot backtest")
            return 0
        return run_synthetic_demo(df, underlying, days)

    # Real Dhan data
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    logger.info(f"Downloading {underlying} {interval}-min data from Dhan ({start} → {end})...")
    df = dhan.get_historical(underlying, interval=str(interval), from_date=start, to_date=end, days=days)
    if df.empty:
        logger.error(f"Dhan returned no data for {underlying}")
        return 0
    logger.info(f"Got {len(df)} bars from Dhan")
    return run_backtest(df, underlying)


def run_synthetic_demo(df, underlying: str, days: int) -> int:
    """Run backtest on whatever data we have (synthetic or otherwise)."""
    return run_backtest(df, underlying)


def run_backtest(df, underlying: str) -> int:
    """Run a backtest on the given OHLCV dataframe."""
    if df is None or df.empty:
        logger.error("No data to backtest")
        return 0
    # try to use the full backtest engine if available
    try:
        from kotak_bot.backtest.engine import BacktestEngine, BacktestConfig
        cfg = BacktestConfig(
            initial_capital=300_000.0,
            commission_per_order=20.0,
            slippage_bps=5.0,
        )
        engine = BacktestEngine(cfg)
        # import strategy
        from kotak_bot.strategy.directional import DirectionalDebitStrategy
        strat = DirectionalDebitStrategy()
        result = engine.run(strat, df, symbol=underlying)
        if result is None:
            logger.warning("Backtest engine returned None — using simple SMA-cross fallback")
            return simple_sma_backtest(df, underlying)
        # print summary
        logger.info(f"\n{'=' * 60}")
        logger.info(f"BACKTEST RESULT — {underlying}")
        logger.info(f"{'=' * 60}")
        if hasattr(result, "metrics"):
            for k, v in result.metrics.items():
                logger.info(f"  {k}: {v}")
        if hasattr(result, "trades") and result.trades is not None:
            logger.info(f"  trades: {len(result.trades)}")
        if hasattr(result, "sharpe_ratio"):
            logger.info(f"  sharpe: {result.sharpe_ratio:.2f}")
        return getattr(result, "sharpe_ratio", 0)
    except ImportError as e:
        logger.warning(f"Full backtest engine not available: {e}")
        return simple_sma_backtest(df, underlying)


def simple_sma_backtest(df, underlying: str) -> int:
    """Simple SMA crossover backtest as a baseline (always works, no strategy import needed)."""
    import pandas as pd
    close = df["close"]
    fast = close.rolling(9).mean()
    slow = close.rolling(21).mean()
    # signals: 1 when fast > slow, 0 otherwise
    signal = (fast > slow).astype(int).fillna(0)
    # returns
    ret = close.pct_change().fillna(0)
    strat_ret = signal.shift(1).fillna(0) * ret
    # metrics
    total_ret = (1 + strat_ret).prod() - 1
    n_periods = len(strat_ret)
    n_years = max(n_periods / (252 * 75), 0.1)  # 75 5-min bars per day
    annual_ret = (1 + total_ret) ** (1 / n_years) - 1
    sharpe = (strat_ret.mean() / max(strat_ret.std(), 1e-9)) * (252 * 75) ** 0.5
    # drawdown
    cum = (1 + strat_ret).cumprod()
    peak = cum.cummax()
    dd = (cum / peak - 1).min()
    n_trades = signal.diff().abs().sum() / 2

    logger.info(f"\n{'=' * 60}")
    logger.info(f"BACKTEST (SMA 9/21 crossover) — {underlying}")
    logger.info(f"{'=' * 60}")
    logger.info(f"  Period: {n_periods} bars ({n_years:.1f} years)")
    logger.info(f"  Total return: {total_ret*100:.1f}%")
    logger.info(f"  Annualized: {annual_ret*100:.1f}%")
    logger.info(f"  Sharpe ratio: {sharpe:.2f}")
    logger.info(f"  Max drawdown: {dd*100:.1f}%")
    logger.info(f"  Trade signals: {n_trades:.0f}")
    return sharpe


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--underlying", default="NIFTY")
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--interval", type=int, default=5, help="minutes")
    args = parser.parse_args()
    sharpe = run_dhan_backtest(args.underlying, args.days, args.interval)
    print(f"\nSharpe: {sharpe:.2f}")
