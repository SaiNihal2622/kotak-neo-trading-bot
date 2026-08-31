"""Historical data fetcher.

Sources (in order of preference):
1. yfinance — FREE, no API key, daily/weekly data for years (best for daily backtest)
2. DhanHQ — FREE with Dhan account, 1-min/5-min historical + option chain
3. nselib — FREE NSE bhav copy, derivatives data (limited)
4. Synthetic — only as last resort

Ticker mapping (yfinance):
- NIFTY 50: ^NSEI
- BANKNIFTY: ^NSEBANK
- SENSEX: ^BSESN
- FINNIFTY: ^CNXIT (NIFTY IT, not FIN NIFTY — use ^NSEBANK for now)
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
from loguru import logger

# yfinance tickers for Indian indices
YFINANCE_TICKERS = {
    "NIFTY": "^NSEI",
    "NIFTY 50": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "SENSEX": "^BSESN",
    "INDIA VIX": "^INDIAVIX",
    "FINNIFTY": "NIFTY_FIN_SERVICE.NS",
    "MIDCPNIFTY": "NIFTY_MID_SELECT.NS",
    # NSE equity tickers (yfinance uses .NS suffix for NSE stocks)
    "RELIANCE": "RELIANCE.NS",
    "HDFCBANK": "HDFCBANK.NS",
    "ICICIBANK": "ICICIBANK.NS",
    "INFY": "INFY.NS",
    "TCS": "TCS.NS",
    "HINDUNILVR": "HINDUNILVR.NS",
    "ITC": "ITC.NS",
    "SBIN": "SBIN.NS",
    "BHARTIARTL": "BHARTIARTL.NS",
    "KOTAKBANK": "KOTAKBANK.NS",
    "LT": "LT.NS",
    "AXISBANK": "AXISBANK.NS",
    "INDUSINDBK": "INDUSINDBK.NS",
    "BAJFINANCE": "BAJFINANCE.NS",
    "ASIANPAINT": "ASIANPAINT.NS",
    "MARUTI": "MARUTI.NS",
    "M&M": "M&M.NS",
    "TATAMOTORS": "TATAMOTORS.NS",
    "TATASTEEL": "TATASTEEL.NS",
    "SUNPHARMA": "SUNPHARMA.NS",
    "HCLTECH": "HCLTECH.NS",
    "POWERGRID": "POWERGRID.NS",
    "NTPC": "NTPC.NS",
    "TITAN": "TITAN.NS",
}


def _yfinance_ticker(symbol: str) -> str:
    """Resolve yfinance ticker for a symbol. Adds .NS for NSE stocks if not in map."""
    s = symbol.upper().strip()
    if s in YFINANCE_TICKERS:
        return YFINANCE_TICKERS[s]
    # Fallback: try .NS suffix for NSE stocks
    return f"{s}.NS"


class HistoricalData:
    """Unified historical data fetcher with disk cache."""

    def __init__(self, source: str = "auto", cache_dir: str = "data_cache/historical", truedata_key: str = ""):
        self.source = source
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.truedata_key = truedata_key
        self.dhan = None
        # init Dhan if creds available
        try:
            from kotak_bot.data.dhan import DhanDataFeed
            self.dhan = DhanDataFeed()
        except Exception:
            pass

    def get_equity_ohlc(self, symbol: str, days: int = 180, interval: str = "1d") -> pd.DataFrame:
        """Get equity/index OHLCV. Tries yfinance first, then Dhan, then nselib, then synthetic."""
        cache = self.cache_dir / f"{symbol}_{interval}_{days}d.parquet"
        if cache.exists() and cache.stat().st_mtime > (datetime.now() - timedelta(hours=12)).timestamp():
            try:
                return pd.read_parquet(cache)
            except Exception:
                pass
        # try yfinance first
        df = self._from_yfinance(symbol, days=days, interval=interval)
        if not df.empty:
            try:
                df.to_parquet(cache)
            except Exception:
                pass
            return df
        # try Dhan
        if self.dhan and self.dhan.enabled:
            df = self.dhan.get_historical(symbol, interval=str(self._interval_to_minutes(interval)), days=days)
            if not df.empty:
                try:
                    df.to_parquet(cache)
                except Exception:
                    pass
                return df
        # try nselib (limited)
        df = self._from_nselib(symbol, days=days)
        if not df.empty:
            try:
                df.to_parquet(cache)
            except Exception:
                pass
            return df
        # last resort: synthetic
        logger.warning(f"No historical data for {symbol} — using synthetic")
        return self._synthetic_ohlc(symbol, days)

    def get_options_chain_history(self, underlying: str, expiry: str, days: int = 30) -> pd.DataFrame:
        """Get historical options chain snapshots (if available)."""
        if self.dhan and self.dhan.enabled:
            return self.dhan.get_option_chain(underlying, expiry)
        return pd.DataFrame()

    def _from_yfinance(self, symbol: str, days: int, interval: str) -> pd.DataFrame:
        """Fetch from yfinance (free, no key)."""
        try:
            import yfinance as yf
            ticker = _yfinance_ticker(symbol)
            # yfinance limit: 1m = 7d, 5m = 60d, 15m = 60d, 1h = 730d, 1d = unlimited
            period = f"{days}d" if interval == "1d" else f"{min(days, 60)}d"
            df = yf.download(ticker, period=period, interval=interval, progress=False)
            if df.empty:
                return df
            # yfinance returns multi-level columns for single ticker
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [c[0] for c in df.columns]
            df = df.reset_index()
            # standardize: date, open, high, low, close, volume
            date_col = "Date" if "Date" in df.columns else "Datetime" if "Datetime" in df.columns else df.columns[0]
            df = df.rename(columns={date_col: "date", "Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})
            df = df[["date", "open", "high", "low", "close", "volume"]]
            df["date"] = pd.to_datetime(df["date"])
            logger.info(f"yfinance [{symbol} {interval}]: {len(df)} rows ({df['date'].min()} -> {df['date'].max()})")
            return df
        except ImportError:
            logger.warning("yfinance not installed — skipping")
            return pd.DataFrame()
        except Exception as e:
            logger.warning(f"yfinance fetch {symbol} failed: {e}")
            return pd.DataFrame()

    def _from_nselib(self, symbol: str, days: int) -> pd.DataFrame:
        """Fetch from nselib (limited support)."""
        try:
            import nselib
            end = datetime.now()
            start = end - timedelta(days=days)
            # nselib uses different method names per version
            if hasattr(nselib, "capital_market_index_data"):
                raw = nselib.capital_market_index_data(index=symbol, from_date=start.strftime("%d-%m-%Y"), to_date=end.strftime("%d-%m-%Y"))
            elif hasattr(nselib, "get_index_data"):
                raw = nselib.get_index_data(symbol)
            else:
                return pd.DataFrame()
            df = pd.DataFrame(raw)
            if df.empty or "TIMESTAMP" not in df.columns:
                return pd.DataFrame()
            df["date"] = pd.to_datetime(df["TIMESTAMP"])
            df = df.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"})
            return df[["date", "open", "high", "low", "close", "volume"]]
        except Exception as e:
            logger.debug(f"nselib {symbol}: {e}")
            return pd.DataFrame()

    def _synthetic_ohlc(self, symbol: str, days: int) -> pd.DataFrame:
        """Generate realistic synthetic OHLC."""
        import numpy as np
        np.random.seed(hash(symbol) % 2**32)
        end = datetime.now()
        if symbol.upper() in ("NIFTY", "NIFTY 50"):
            dates = pd.bdate_range(end=end, periods=days)
            base = 24500
            vol = 0.012
        elif "BANKNIFTY" in symbol.upper():
            dates = pd.bdate_range(end=end, periods=days)
            base = 52000
            vol = 0.016
        else:
            dates = pd.bdate_range(end=end, periods=days)
            base = 5000
            vol = 0.018
        returns = np.random.normal(0.0004, vol, size=len(dates))
        close = base * (1 + pd.Series(returns)).cumprod()
        open_ = close.shift(1).fillna(base)
        high = pd.concat([open_, close], axis=1).max(axis=1) * (1 + np.abs(np.random.normal(0, 0.005, size=len(dates))))
        low = pd.concat([open_, close], axis=1).min(axis=1) * (1 - np.abs(np.random.normal(0, 0.005, size=len(dates))))
        return pd.DataFrame({
            "date": dates,
            "open": open_.round(2),
            "high": high.round(2),
            "low": low.round(2),
            "close": close.round(2),
            "volume": np.random.randint(100000, 5000000, size=len(dates)),
        })

    @staticmethod
    def _interval_to_minutes(interval: str) -> int:
        return {"1d": 1440, "1h": 60, "15m": 15, "5m": 5, "1m": 1}.get(interval, 5)
