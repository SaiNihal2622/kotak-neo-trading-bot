"""
backtest/engine.py
==================

Vectorbt-based backtester for Indian options strategies.

Provides:

* ``BacktestConfig``  — dataclass holding capital, fees, slippage, and
  Indian-market specific knobs (lot size, square-off window, etc.).
* ``Strategy``        — abstract base class. Subclasses emit entry / exit /
  sizing signals from a feature-augmented OHLCV frame.
* ``BacktestEngine``  — runs a strategy on historical data via ``vectorbt``,
  computes standard performance metrics, and produces a ``BacktestResult``.
* ``walk_forward``    — splits data into N chronological folds and returns a
  list of out-of-sample ``BacktestResult`` objects.
* ``report``          — writes a JSON metrics file, a CSV of trades, and a
  PNG equity curve to disk.
* ``generate_synthetic_data`` — geometric-Brownian-motion simulator with
  regime switches (trend / range / volatile), intraday volatility smile, and
  deterministic seed for reproducible smoke tests.

Run as a smoke test::

    python -m backtest.engine

The smoke test generates 5,000 bars of synthetic NIFTY-style 5-minute data,
runs a dual-EMA crossover strategy, prints the metrics, and writes a report
to ``backtest/results/smoke/``.

Graceful degradation
-------------------

* If ``vectorbt`` is not installed, the engine falls back to a tiny
  vectorised P&L simulator that still produces metrics and an equity curve.
* If ``pandas_ta`` is not installed, indicators are computed manually with
  ``pandas`` / ``numpy``.

Author: Kotak Neo Bot project
"""

from __future__ import annotations

import hashlib
import json
import math
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, Optional, Union

import numpy as np
import pandas as pd

# Matplotlib is used only for the PNG equity curve in ``report``.
import matplotlib

matplotlib.use("Agg")  # headless backend — no DISPLAY required
import matplotlib.pyplot as plt

from loguru import logger

# ---------------------------------------------------------------------------
# Optional third-party imports — handled with graceful degradation
# ---------------------------------------------------------------------------
try:
    import vectorbt as vbt

    _HAS_VBT = True
except Exception as _exc:  # pragma: no cover - exercised only if missing
    _HAS_VBT = False
    vbt = None  # type: ignore[assignment]
    logger.warning("vectorbt not installed — BacktestEngine will use the dry-run simulator")

try:
    import pandas_ta as pta

    _HAS_PTA = True
except Exception:  # pragma: no cover
    _HAS_PTA = False
    pta = None  # type: ignore[assignment]
    logger.warning("pandas_ta not installed — indicators will be computed manually")


# ===========================================================================
# Indian market constants
# ===========================================================================

# Lot sizes as published by NSE. Single source of truth for the project.
LOT_SIZES: dict[str, int] = {
    "NIFTY": 25,
    "BANKNIFTY": 15,
    "FINNIFTY": 25,
    "MIDCPNIFTY": 50,
    "SENSEX": 10,
    "BANKEX": 15,
}

# Symbols with a weekly (Thursday) expiry.
WEEKLY_EXPIRY_SYMBOLS: frozenset[str] = frozenset(
    {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"}
)

# NSE cash & derivatives segment hours (IST).
MARKET_OPEN_TIME: time = time(9, 15)
MARKET_CLOSE_TIME: time = time(15, 30)
OPENING_RANGE_START: time = time(9, 0)
OPENING_RANGE_END: time = time(9, 15)
SQUARE_OFF_START: time = time(15, 15)
SQUARE_OFF_END: time = time(15, 30)


# ===========================================================================
# Indian market helpers
# ===========================================================================


def get_lot_size(symbol: str) -> int:
    """Return the NSE lot size for ``symbol``. Defaults to 1 if unknown."""
    if not symbol:
        return 1
    return LOT_SIZES.get(symbol.upper(), 1)


def is_weekly_expiry(d: Union[datetime, pd.Timestamp]) -> bool:
    """``True`` if ``d`` falls on a Thursday (NIFTY / BANKNIFTY expiry)."""
    return pd.Timestamp(d).weekday() == 3  # Monday=0, Thursday=3


def next_weekly_expiry(d: Union[datetime, pd.Timestamp]) -> pd.Timestamp:
    """Return the next Thursday on or after ``d`` (weekly expiry helper)."""
    ts = pd.Timestamp(d)
    days_ahead = (3 - ts.weekday()) % 7
    if days_ahead == 0 and ts.time() >= time(15, 30):
        days_ahead = 7
    return ts.normalize() + pd.Timedelta(days=days_ahead)


def in_opening_range(ts: Union[datetime, pd.Timestamp]) -> bool:
    """``True`` for 09:00 – 09:15 IST opening range (no fresh entries)."""
    t = pd.Timestamp(ts).time()
    return OPENING_RANGE_START <= t < OPENING_RANGE_END


def in_square_off_window(ts: Union[datetime, pd.Timestamp]) -> bool:
    """``True`` for 15:15 – 15:30 IST mandatory square-off window."""
    t = pd.Timestamp(ts).time()
    return SQUARE_OFF_START <= t <= SQUARE_OFF_END


def is_market_hours(ts: Union[datetime, pd.Timestamp]) -> bool:
    """``True`` for 09:15 – 15:30 IST cash/derivatives session."""
    t = pd.Timestamp(ts).time()
    return MARKET_OPEN_TIME <= t <= MARKET_CLOSE_TIME


# ===========================================================================
# Indicator computation
# ===========================================================================


def _rsi(close: pd.Series, length: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()
    avg_loss = loss.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi.fillna(50.0)


def _macd(
    close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    sig = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - sig
    return macd_line, sig, hist


def _bollinger(
    close: pd.Series, length: int = 20, std: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = close.rolling(length).mean()
    sd = close.rolling(length).std(ddof=0)
    return mid + std * sd, mid, mid - std * sd


def _atr(df: pd.DataFrame, length: int = 14) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()


def _adx(df: pd.DataFrame, length: int = 14) -> pd.Series:
    high = df["high"]
    low = df["low"]
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    atr = _atr(df, length)
    plus_di = 100.0 * pd.Series(plus_dm, index=df.index).ewm(
        alpha=1.0 / length, adjust=False, min_periods=length
    ).mean() / atr.replace(0.0, np.nan)
    minus_di = 100.0 * pd.Series(minus_dm, index=df.index).ewm(
        alpha=1.0 / length, adjust=False, min_periods=length
    ).mean() / atr.replace(0.0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)
    adx = dx.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()
    return adx.fillna(20.0)


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Augment ``df`` with RSI, MACD, Bollinger, EMAs, ADX, ATR, and an IV proxy.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain ``open``, ``high``, ``low``, ``close``, ``volume`` columns
        and a ``DatetimeIndex`` (any frequency).

    Returns
    -------
    pd.DataFrame
        A new frame with the original columns plus the indicators.
    """
    if df.empty:
        return df.copy()

    df = df.copy()
    df.columns = [str(c).lower() for c in df.columns]
    close = df["close"]

    if _HAS_PTA:
        try:
            df.ta.rsi(length=14, append=True)
            df.ta.macd(fast=12, slow=26, signal=9, append=True)
            df.ta.bbands(length=20, std=2, append=True)
            df.ta.ema(length=9, append=True)
            df.ta.ema(length=21, append=True)
            df.ta.ema(length=50, append=True)
            df.ta.adx(length=14, append=True)
            df.ta.atr(length=14, append=True)
        except Exception as exc:
            logger.warning(f"pandas_ta failed ({exc}); falling back to manual indicators")
            _add_manual_indicators(df, close)
    else:
        _add_manual_indicators(df, close)

    # Realised-volatility proxy, annualised. ``bars_per_year`` is auto-computed
    # from the index frequency so the same code works for 1-min, 5-min, daily.
    if len(df.index) >= 2:
        inferred = pd.infer_freq(df.index)
        bars_per_year = _bars_per_year(inferred)
        ret = close.pct_change()
        df["iv_proxy"] = (ret.rolling(20).std() * np.sqrt(bars_per_year)).fillna(0.0)
    else:
        df["iv_proxy"] = 0.0

    return df


def _add_manual_indicators(df: pd.DataFrame, close: pd.Series) -> None:
    """In-place fallback when ``pandas_ta`` is unavailable."""
    df["RSI_14"] = _rsi(close, 14)
    macd, signal, hist = _macd(close)
    df["MACD_12_26_9"] = macd
    df["MACDs_12_26_9"] = signal
    df["MACDh_12_26_9"] = hist
    upper, mid, lower = _bollinger(close)
    df["BBU_20_2.0"] = upper
    df["BBM_20_2.0"] = mid
    df["BBL_20_2.0"] = lower
    df["EMA_9"] = close.ewm(span=9, adjust=False).mean()
    df["EMA_21"] = close.ewm(span=21, adjust=False).mean()
    df["EMA_50"] = close.ewm(span=50, adjust=False).mean()
    df["ADX_14"] = _adx(df, 14)
    df["ATRr_14"] = _atr(df, 14)


def _bars_per_year(freq: Optional[str]) -> int:
    """Convert a pandas frequency string to an approximate bars-per-year count."""
    if not freq:
        return 252 * 75  # 5-min default
    f = freq.upper()
    if "MIN" in f or "T" in f:
        try:
            minutes = int(f.split("MIN")[0].split("T")[0] or "1")
            # 6.25 trading hours × 60 min = 375 minutes per day × 252 days
            return int(375 * 252 / max(minutes, 1))
        except Exception:
            return 252 * 75
    if "H" in f:
        return int(252 * 6.25)
    if "D" in f:
        return 252
    if "W" in f:
        return 52
    return 252


# ===========================================================================
# Synthetic data generator
# ===========================================================================


def generate_synthetic_data(
    n_bars: int = 5000,
    start_price: float = 18000.0,
    freq: str = "5min",
    seed: int = 42,
    start: str = "2023-01-02 09:15",
) -> pd.DataFrame:
    """Geometric-Brownian-motion OHLCV with regime switches and intraday vol smile.

    Parameters
    ----------
    n_bars : int
        Number of bars to simulate.
    start_price : float
        Starting close.
    freq : str
        Any pandas frequency string, e.g. ``"5min"`` or ``"1D"``.
    seed : int
        RNG seed — deterministic for reproducible tests.
    start : str
        Timestamp of the first bar.

    Returns
    -------
    pd.DataFrame
        Indexed by ``DatetimeIndex`` (IST-naive). Columns:
        ``open``, ``high``, ``low``, ``close``, ``volume``, ``regime``.
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range(start=start, periods=n_bars, freq=freq)

    # ---- regime sequence: alternating trend / range / volatile runs -------
    regime = np.zeros(n_bars, dtype=np.int8)
    pos = 0
    while pos < n_bars:
        run_len = int(rng.integers(50, 200))
        run_len = min(run_len, n_bars - pos)
        regime[pos : pos + run_len] = int(rng.choice([0, 1, 2]))  # 0=trend,1=range,2=volatile
        pos += run_len

    # Drift & base volatility per regime.
    drift = np.where(regime == 0, 0.00010, np.where(regime == 1, 0.0, -0.00008))
    base_vol = np.where(regime == 0, 0.00080, np.where(regime == 1, 0.00050, 0.00150))

    # Intraday vol smile: higher near open (09:30) and close (15:00).
    minutes_of_day = dates.hour * 60 + dates.minute
    tod_mult = (
        1.0
        + 0.6 * np.exp(-((minutes_of_day - 9 * 60 - 30) ** 2) / (2 * 30.0**2))
        + 0.6 * np.exp(-((minutes_of_day - 15 * 60) ** 2) / (2 * 30.0**2))
    )
    vol = base_vol * tod_mult

    # ---- GBM path ---------------------------------------------------------
    noise = rng.normal(loc=drift, scale=vol)
    log_close = np.cumsum(np.log1p(noise))
    close = start_price * np.exp(log_close - np.cumsum(drift) + drift.cumsum() * 0.0)
    close = np.maximum(close, 1.0)

    # OHLC around the close: each bar has some intraperiod excursion.
    intrabar = np.abs(rng.normal(0.0, 0.0008, n_bars))
    high = close * (1.0 + intrabar)
    low = close * (1.0 - intrabar)
    opn = np.concatenate([[close[0]], close[:-1]]) * (1.0 + rng.normal(0.0, 0.0003, n_bars))
    opn = np.maximum(opn, low)
    high = np.maximum(high, np.maximum(opn, close))
    low = np.minimum(low, np.minimum(opn, close))
    volume = rng.integers(1_000, 100_000, n_bars).astype(np.int64)

    df = pd.DataFrame(
        {
            "open": opn,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "regime": regime,
        },
        index=dates,
    )
    df.index.name = "timestamp"
    return df


# ===========================================================================
# Configuration & result dataclasses
# ===========================================================================


@dataclass
class BacktestConfig:
    """Static configuration for a backtest run.

    Attributes
    ----------
    initial_capital : float
        Starting cash in INR.
    commission_per_lot : float
        Flat brokerage charged per *lot* (round-trip) — typical Zerodha-style.
    slippage_bps : float
        One-way slippage in basis points (1 bp = 0.01 %).
    symbol : str
        Underlying symbol — used to look up lot size.
    risk_free_rate : float
        Annualised risk-free rate for Sharpe / Sortino (India 10Y ~ 0.07).
    freq : str
        Bar frequency of the price series, e.g. ``"5min"``.
    output_dir : str
        Default directory for ``report()``.
    enforce_market_hours : bool
        If ``True``, suppress entries in the opening range and force exits in
        the square-off window.
    apply_lot_size : bool
        If ``True`` and the strategy returns a fractional size, round up to
        whole lots.
    start_date, end_date : Optional[str]
        ISO-format filter applied during ``load_data``.
    """

    initial_capital: float = 1_000_000.0
    commission_per_lot: float = 50.0
    slippage_bps: float = 2.0
    symbol: str = "NIFTY"
    risk_free_rate: float = 0.07
    freq: str = "5min"
    output_dir: str = "backtest/results"
    enforce_market_hours: bool = True
    apply_lot_size: bool = True
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)

    def lot_size(self) -> int:
        return get_lot_size(self.symbol)


@dataclass
class BacktestResult:
    """Outcome of a single backtest run.

    Attributes
    ----------
    metrics : dict
        Aggregate performance metrics (Sharpe, Sortino, max DD, etc.).
    trades : pd.DataFrame
        Per-trade records — vectorbt's ``trades.records_readable``.
    equity_curve : pd.Series
        Mark-to-market portfolio value over time.
    config : BacktestConfig
        The configuration used for this run.
    strategy_name : str
        Class name of the strategy.
    fold_index : Optional[int]
        For walk-forward runs, the 0-based fold number. ``None`` for a
        single-shot run.
    """

    metrics: dict[str, float]
    trades: pd.DataFrame
    equity_curve: pd.Series
    config: BacktestConfig
    strategy_name: str
    fold_index: Optional[int] = None

    @property
    def is_profitable(self) -> bool:
        return float(self.metrics.get("total_return", 0.0)) > 0.0


# ===========================================================================
# Strategy abstract base class
# ===========================================================================


class Strategy(ABC):
    """Base class for vectorbt-driven strategies.

    Subclasses must implement :meth:`entry_signals` and :meth:`exit_signals`.
    The default :meth:`position_size` returns 1 lot per signal.

    ``params`` is a public attribute that walk-forward optimisers can mutate
    between folds; the framework does not introspect it.
    """

    name: str = "BaseStrategy"
    params: dict[str, Any] = {}

    def __init__(self, **params: Any) -> None:
        self.params = {**self.params, **params}

    @abstractmethod
    def entry_signals(self, df: pd.DataFrame) -> pd.Series:
        """Boolean series — ``True`` on bars where a long entry is taken."""

    @abstractmethod
    def exit_signals(self, df: pd.DataFrame) -> pd.Series:
        """Boolean series — ``True`` on bars where the long is closed."""

    def position_size(self, df: pd.DataFrame) -> pd.Series:
        """Return desired position *units* (number of contracts) per bar.

        Default: 1 contract on any bar where entry is allowed.
        """
        return pd.Series(1.0, index=df.index)

    def get_params(self) -> dict[str, Any]:
        return dict(self.params)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<{self.name} params={self.get_params()}>"


# ---------------------------------------------------------------------------
# Built-in strategies
# ---------------------------------------------------------------------------


class EMACrossStrategy(Strategy):
    """Long-only dual-EMA crossover with optional RSI filter.

    Parameters
    ----------
    fast : int
        Fast EMA length.
    slow : int
        Slow EMA length.
    rsi_filter : float | None
        If set, only enter when RSI < this value (mean-reversion filter).
    """

    name = "EMACross"

    def __init__(self, fast: int = 9, slow: int = 21, rsi_filter: Optional[float] = None) -> None:
        super().__init__(fast=fast, slow=slow, rsi_filter=rsi_filter)
        self.fast = fast
        self.slow = slow
        self.rsi_filter = rsi_filter

    def entry_signals(self, df: pd.DataFrame) -> pd.Series:
        fast_col = f"EMA_{self.fast}"
        slow_col = f"EMA_{self.slow}"
        if fast_col not in df.columns or slow_col not in df.columns:
            logger.error(f"EMACross requires {fast_col} and {slow_col}")
            return pd.Series(False, index=df.index)
        cross_up = (df[fast_col] > df[slow_col]) & (df[fast_col].shift(1) <= df[slow_col].shift(1))
        if self.rsi_filter is not None and "RSI_14" in df.columns:
            cross_up = cross_up & (df["RSI_14"] < self.rsi_filter)
        return cross_up.fillna(False).astype(bool)

    def exit_signals(self, df: pd.DataFrame) -> pd.Series:
        fast_col = f"EMA_{self.fast}"
        slow_col = f"EMA_{self.slow}"
        cross_down = (df[fast_col] < df[slow_col]) & (df[fast_col].shift(1) >= df[slow_col].shift(1))
        return cross_down.fillna(False).astype(bool)


class RSIMeanReversionStrategy(Strategy):
    """Long when RSI is oversold, exit when it reverts to the midline.

    Parameters
    ----------
    lower : float
        RSI level that triggers an entry (e.g. 30).
    upper : float
        RSI level that triggers an exit (e.g. 50).
    """

    name = "RSIMeanReversion"

    def __init__(self, lower: float = 30.0, upper: float = 50.0) -> None:
        super().__init__(lower=lower, upper=upper)
        self.lower = lower
        self.upper = upper

    def entry_signals(self, df: pd.DataFrame) -> pd.Series:
        if "RSI_14" not in df.columns:
            return pd.Series(False, index=df.index)
        return (df["RSI_14"] < self.lower).fillna(False).astype(bool)

    def exit_signals(self, df: pd.DataFrame) -> pd.Series:
        if "RSI_14" not in df.columns:
            return pd.Series(False, index=df.index)
        return (df["RSI_14"] > self.upper).fillna(False).astype(bool)


class BollingerBreakoutStrategy(Strategy):
    """Enter on close > upper band, exit on close < mid band.

    Useful for momentum regimes.
    """

    name = "BollingerBreakout"

    def __init__(self, std: float = 2.0, length: int = 20) -> None:
        super().__init__(std=std, length=length)

    def entry_signals(self, df: pd.DataFrame) -> pd.Series:
        upper = f"BBU_20_2.0"
        if upper not in df.columns:
            return pd.Series(False, index=df.index)
        return (df["close"] > df[upper]).fillna(False).astype(bool)

    def exit_signals(self, df: pd.DataFrame) -> pd.Series:
        mid = "BBM_20_2.0"
        if mid not in df.columns:
            return pd.Series(False, index=df.index)
        return (df["close"] < df[mid]).fillna(False).astype(bool)


# ===========================================================================
# Engine
# ===========================================================================


class BacktestEngine:
    """Run a ``Strategy`` against historical OHLCV data via vectorbt.

    Typical usage::

        cfg = BacktestConfig(initial_capital=1_000_000, symbol="NIFTY")
        engine = BacktestEngine(cfg)
        engine.load_data(generate_synthetic_data(n_bars=2000))
        result = engine.run(EMACrossStrategy())
        engine.report(result, "backtest/results/demo")

    Parameters
    ----------
    config : BacktestConfig
        Static configuration.
    """

    def __init__(self, config: BacktestConfig) -> None:
        self.config = config
        self._data: Optional[pd.DataFrame] = None
        logger.info(
            f"BacktestEngine ready — capital={config.initial_capital:,.0f} "
            f"symbol={config.symbol} lot={config.lot_size()} "
            f"fees={config.commission_per_lot}/lot slippage={config.slippage_bps}bp"
        )

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------
    def load_data(self, source: Union[str, Path, pd.DataFrame]) -> pd.DataFrame:
        """Load OHLCV from a CSV path or accept a DataFrame directly.

        Parameters
        ----------
        source : str | Path | pd.DataFrame
            * ``pd.DataFrame`` — used as-is, must contain OHLCV columns.
            * ``str`` / ``Path`` — path to a CSV. The first column is treated
              as the timestamp index.

        Returns
        -------
        pd.DataFrame
            The bar frame stored on the engine.
        """
        if isinstance(source, (str, Path)):
            csv_path = Path(source)
            if not csv_path.exists():
                raise FileNotFoundError(f"CSV not found: {csv_path}")
            logger.info(f"Loading CSV: {csv_path}")
            df = pd.read_csv(csv_path, index_col=0, parse_dates=True)
        elif isinstance(source, pd.DataFrame):
            df = source.copy()
        else:
            raise TypeError(f"Unsupported source type: {type(source)!r}")

        # Normalise column names
        df.columns = [str(c).lower().strip() for c in df.columns]
        required = {"open", "high", "low", "close", "volume"}
        missing = required - set(df.columns)
        if missing:
            if missing == {"volume"}:
                df["volume"] = 0
            else:
                raise ValueError(f"OHLCV frame is missing required columns: {missing}")

        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)
        df = df.sort_index()

        if self.config.start_date:
            df = df[df.index >= pd.Timestamp(self.config.start_date)]
        if self.config.end_date:
            df = df[df.index <= pd.Timestamp(self.config.end_date)]

        logger.info(
            f"Loaded {len(df):,} bars from {df.index[0]} to {df.index[-1]} "
            f"(freq≈{pd.infer_freq(df.index)})"
        )
        self._data = df
        return df

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def run(self, strategy: Strategy) -> BacktestResult:
        """Run a backtest and return a populated ``BacktestResult``."""
        if self._data is None:
            raise RuntimeError("No data loaded. Call load_data() first.")
        return self._run_on_data(strategy, self._data, fold_index=None)

    def walk_forward(
        self, strategy: Strategy, n_splits: int = 5
    ) -> list[BacktestResult]:
        """Walk-forward analysis: N chronological folds, OOS test on each.

        For each fold ``i`` in ``[0, n_splits)``:
        * Train slice =  ``[i*fold_size, (i+1)*fold_size)``
        * Test slice  =  ``[(i+1)*fold_size, (i+2)*fold_size)``

        The strategy object is reused; subclasses can override
        ``strategy.optimize(train_df)`` if they want per-fold parameter
        tuning (default = no optimisation, just OOS run).
        """
        if self._data is None:
            raise RuntimeError("No data loaded. Call load_data() first.")
        if n_splits < 2:
            raise ValueError("n_splits must be >= 2 for walk-forward analysis")

        df = self._data
        n = len(df)
        fold_size = n // (n_splits + 1)
        if fold_size < 50:
            raise ValueError(
                f"Dataset too small ({n} bars) for {n_splits}-fold walk-forward"
            )

        logger.info(
            f"Walk-forward: {n_splits} folds × {fold_size} bars, total={n:,}"
        )
        results: list[BacktestResult] = []
        for i in range(n_splits):
            train_slice = df.iloc[i * fold_size : (i + 1) * fold_size]
            test_slice = df.iloc[(i + 1) * fold_size : (i + 2) * fold_size]
            if test_slice.empty:
                break
            if hasattr(strategy, "optimize"):
                try:
                    strategy.optimize(train_slice)  # type: ignore[attr-defined]
                except Exception as exc:
                    logger.warning(f"Fold {i}: strategy.optimize failed: {exc}")
            result = self._run_on_data(strategy, test_slice, fold_index=i)
            result.metrics["fold_train_bars"] = len(train_slice)
            result.metrics["fold_test_bars"] = len(test_slice)
            results.append(result)
            logger.info(
                f"  Fold {i}: return={result.metrics.get('total_return', 0):+.2%} "
                f"sharpe={result.metrics.get('sharpe', 0):.2f} "
                f"DD={result.metrics.get('max_drawdown', 0):+.2%}"
            )
        return results

    def report(
        self,
        result: BacktestResult,
        path: Optional[Union[str, Path]] = None,
        walk_forward_results: Optional[list[BacktestResult]] = None,
    ) -> None:
        """Write JSON metrics, CSV trades, and a PNG equity curve.

        Parameters
        ----------
        result : BacktestResult
        path : str | Path | None
            Directory to write into. Defaults to ``config.output_dir``.
        walk_forward_results : list[BacktestResult] | None
            If provided, an additional ``walk_forward_summary.json`` is written
            and an aggregated equity curve PNG is produced.
        """
        out_dir = Path(path) if path else Path(self.config.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        # ---- JSON metrics ------------------------------------------------
        with open(out_dir / "metrics.json", "w", encoding="utf-8") as fh:
            json.dump(_jsonable(result.metrics), fh, indent=2, default=str)

        # ---- CSV trades --------------------------------------------------
        if not result.trades.empty:
            result.trades.to_csv(out_dir / "trades.csv", index=False)
        else:
            (out_dir / "trades.csv").write_text("no trades\n", encoding="utf-8")

        # ---- PNG equity curve -------------------------------------------
        self._plot_equity(result.equity_curve, result.strategy_name, out_dir / "equity_curve.png")

        # ---- Walk-forward artefacts -------------------------------------
        if walk_forward_results:
            summary = _aggregate_walk_forward(walk_forward_results)
            with open(out_dir / "walk_forward_summary.json", "w", encoding="utf-8") as fh:
                json.dump(summary, fh, indent=2, default=str)
            self._plot_walk_forward(walk_forward_results, out_dir / "walk_forward_equity.png")

        logger.success(f"Report written to {out_dir}")

    # ------------------------------------------------------------------
    # Internal: run on a data slice
    # ------------------------------------------------------------------
    def _run_on_data(
        self, strategy: Strategy, data: pd.DataFrame, fold_index: Optional[int]
    ) -> BacktestResult:
        df = compute_indicators(data)

        entries = strategy.entry_signals(df).fillna(False).astype(bool)
        exits = strategy.exit_signals(df).fillna(False).astype(bool)
        size = strategy.position_size(df).fillna(0.0)

        if self.config.enforce_market_hours:
            valid = pd.Series(
                [is_market_hours(t) and not in_opening_range(t) for t in df.index],
                index=df.index,
            )
            entries = entries & valid
            exits = exits | (~valid)

        if self.config.apply_lot_size:
            lot = max(self.config.lot_size(), 1)
            size = np.ceil(size / lot) * lot

        if _HAS_VBT:
            return self._run_vectorbt(df, entries, exits, size, strategy, fold_index)
        return self._run_dry(df, entries, exits, size, strategy, fold_index)

    # -- vectorbt path ---------------------------------------------------
    def _run_vectorbt(
        self,
        df: pd.DataFrame,
        entries: pd.Series,
        exits: pd.Series,
        size: pd.Series,
        strategy: Strategy,
        fold_index: Optional[int],
    ) -> BacktestResult:
        portfolio = vbt.Portfolio.from_signals(
            close=df["close"],
            entries=entries,
            exits=exits,
            size=size,
            size_type="amount",
            init_cash=self.config.initial_capital,
            fees=self.config.commission_per_lot,
            slippage=self.config.slippage_bps / 10_000.0,
            freq=self.config.freq,
        )
        metrics = self._extract_metrics(portfolio)
        trades = (
            portfolio.trades.records_readable
            if len(portfolio.trades.records) > 0
            else pd.DataFrame()
        )
        equity = portfolio.value()
        return BacktestResult(
            metrics=metrics,
            trades=trades,
            equity_curve=equity,
            config=self.config,
            strategy_name=strategy.name,
            fold_index=fold_index,
        )

    # -- dry-run fallback path ------------------------------------------
    def _run_dry(
        self,
        df: pd.DataFrame,
        entries: pd.Series,
        exits: pd.Series,
        size: pd.Series,
        strategy: Strategy,
        fold_index: Optional[int],
    ) -> BacktestResult:
        """Tiny vectorised P&L simulator used when vectorbt is missing."""
        cash = float(self.config.initial_capital)
        position = 0.0
        entry_price = 0.0
        entry_time: Optional[pd.Timestamp] = None
        equity = pd.Series(index=df.index, dtype=float)
        trade_records: list[dict[str, Any]] = []

        for ts, row in df.iterrows():
            px = float(row["close"])
            units = float(size.loc[ts]) if ts in size.index else 0.0
            if position == 0.0 and bool(entries.loc[ts]) and units > 0:
                position = units
                entry_price = px * (1.0 + self.config.slippage_bps / 10_000.0)
                entry_time = ts
            elif position > 0.0 and (bool(exits.loc[ts]) or units == 0):
                exit_price = px * (1.0 - self.config.slippage_bps / 10_000.0)
                pnl = (exit_price - entry_price) * position
                lots = max(int(position // max(self.config.lot_size(), 1)), 1)
                pnl -= self.config.commission_per_lot * lots * 2  # round-trip
                cash += position * exit_price
                trade_records.append(
                    {
                        "Entry Timestamp": entry_time,
                        "Exit Timestamp": ts,
                        "Avg Entry Price": entry_price,
                        "Avg Exit Price": exit_price,
                        "Size": position,
                        "PnL": pnl,
                        "Return": pnl / max(entry_price * position, 1.0),
                    }
                )
                position = 0.0
                entry_price = 0.0
                entry_time = None
            equity.loc[ts] = cash + position * px

        if position > 0.0 and len(df) > 0:
            # Force close at last bar
            last_ts = df.index[-1]
            last_px = float(df["close"].iloc[-1])
            exit_price = last_px * (1.0 - self.config.slippage_bps / 10_000.0)
            pnl = (exit_price - entry_price) * position
            cash += position * exit_price
            trade_records.append(
                {
                    "Entry Timestamp": entry_time,
                    "Exit Timestamp": last_ts,
                    "Avg Entry Price": entry_price,
                    "Avg Exit Price": exit_price,
                    "Size": position,
                    "PnL": pnl,
                    "Return": pnl / max(entry_price * position, 1.0),
                }
            )
            equity.iloc[-1] = cash

        trades = pd.DataFrame(trade_records)
        metrics = self._metrics_from_trades(trades, equity)
        return BacktestResult(
            metrics=metrics,
            trades=trades,
            equity_curve=equity,
            config=self.config,
            strategy_name=strategy.name,
            fold_index=fold_index,
        )

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------
    def _extract_metrics(self, portfolio: Any) -> dict[str, float]:
        """Compute the canonical metrics from a vectorbt portfolio object."""
        try:
            total_return = float(portfolio.total_return())
        except Exception:
            total_return = 0.0
        try:
            sharpe = float(portfolio.sharpe_ratio())
        except Exception:
            sharpe = 0.0
        try:
            sortino = float(portfolio.sortino_ratio())
        except Exception:
            sortino = 0.0
        try:
            max_dd = float(portfolio.max_drawdown())
        except Exception:
            max_dd = 0.0

        n_trades = 0
        win_rate = 0.0
        profit_factor = 0.0
        avg_win = 0.0
        avg_loss = 0.0
        payoff = 0.0
        if hasattr(portfolio, "trades") and len(portfolio.trades.records) > 0:
            t = portfolio.trades
            n_trades = int(len(t.records))
            try:
                win_rate = float(t.win_rate())
            except Exception:
                pass
            try:
                wins = t.winning.values if hasattr(t, "winning") else None
                losses = t.losing.values if hasattr(t, "losing") else None
            except Exception:
                wins = losses = None
            if wins is not None and len(wins) > 0:
                avg_win = float(np.mean(wins)) if np.any(wins) else 0.0
            if losses is not None and len(losses) > 0:
                avg_loss = float(np.mean(losses)) if np.any(losses) else 0.0
                if avg_loss != 0:
                    profit_factor = abs(avg_win * np.sum(wins)) / abs(avg_loss * np.sum(losses))
            if avg_loss != 0:
                payoff = abs(avg_win / avg_loss) if avg_loss != 0 else 0.0

        return {
            "total_return": total_return,
            "sharpe": sharpe,
            "sortino": sortino,
            "max_drawdown": max_dd,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "payoff_index": payoff,
            "n_trades": n_trades,
        }

    def _metrics_from_trades(
        self, trades: pd.DataFrame, equity: pd.Series
    ) -> dict[str, float]:
        """Same metric shape as :meth:`_extract_metrics` but for the dry-run path."""
        if trades.empty or equity.empty:
            return {
                "total_return": 0.0,
                "sharpe": 0.0,
                "sortino": 0.0,
                "max_drawdown": 0.0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "payoff_index": 0.0,
                "n_trades": 0,
            }
        pnl = trades["PnL"].astype(float)
        wins = pnl[pnl > 0]
        losses = pnl[pnl < 0]
        total_return = float(equity.iloc[-1] / equity.iloc[0] - 1.0) if equity.iloc[0] else 0.0
        ret = equity.pct_change().dropna()
        if ret.std() and not math.isnan(ret.std()):
            sharpe = float(ret.mean() / ret.std() * np.sqrt(252 * 75))
        else:
            sharpe = 0.0
        downside = ret[ret < 0]
        if len(downside) and downside.std():
            sortino = float(ret.mean() / downside.std() * np.sqrt(252 * 75))
        else:
            sortino = sharpe
        running_max = equity.cummax()
        max_dd = float((equity / running_max - 1.0).min())
        avg_win = float(wins.mean()) if len(wins) else 0.0
        avg_loss = float(losses.mean()) if len(losses) else 0.0
        win_rate = float(len(wins) / max(len(pnl), 1))
        gross_win = float(wins.sum()) if len(wins) else 0.0
        gross_loss = float(losses.sum()) if len(losses) else 0.0
        profit_factor = abs(gross_win / gross_loss) if gross_loss else 0.0
        payoff = abs(avg_win / avg_loss) if avg_loss else 0.0
        return {
            "total_return": total_return,
            "sharpe": sharpe,
            "sortino": sortino,
            "max_drawdown": max_dd,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "payoff_index": payoff,
            "n_trades": int(len(trades)),
        }

    # ------------------------------------------------------------------
    # Plotting
    # ------------------------------------------------------------------
    def _plot_equity(
        self, equity: pd.Series, title: str, out_path: Path
    ) -> None:
        if equity.empty:
            logger.warning("Empty equity curve — skipping PNG")
            return
        fig, ax = plt.subplots(figsize=(12, 6))
        equity.plot(ax=ax, color="#1f77b4", linewidth=1.4)
        ax.set_title(f"{title} — Equity Curve")
        ax.set_ylabel("Portfolio Value (INR)")
        ax.set_xlabel("Time")
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        fig.savefig(out_path, dpi=120)
        plt.close(fig)

    def _plot_walk_forward(
        self, results: list[BacktestResult], out_path: Path
    ) -> None:
        if not results:
            return
        fig, axes = plt.subplots(1, 2, figsize=(14, 5))
        for r in results:
            if r.equity_curve.empty:
                continue
            label = f"fold {r.fold_index}"
            axes[0].plot(r.equity_curve.index, r.equity_curve.values, label=label)
            axes[1].bar(label, r.metrics.get("total_return", 0.0))
        axes[0].set_title("Walk-Forward Equity Curves (OOS)")
        axes[0].set_ylabel("Portfolio Value (INR)")
        axes[0].grid(True, alpha=0.3)
        axes[0].legend(fontsize=8)
        axes[1].set_title("Per-Fold Return")
        axes[1].set_ylabel("Total Return")
        axes[1].axhline(0, color="black", linewidth=0.6)
        axes[1].grid(True, alpha=0.3)
        fig.tight_layout()
        fig.savefig(out_path, dpi=120)
        plt.close(fig)


# ===========================================================================
# Helpers
# ===========================================================================


def _jsonable(obj: Any) -> Any:
    """Recursively coerce numpy / pandas types to native Python for JSON."""
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (np.floating, np.integer)):
        return obj.item()
    if isinstance(obj, (pd.Timestamp, datetime)):
        return obj.isoformat()
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


def _aggregate_walk_forward(results: list[BacktestResult]) -> dict[str, Any]:
    """Aggregate per-fold OOS metrics into a single summary dict."""
    if not results:
        return {"n_folds": 0}
    keys = [
        "total_return",
        "sharpe",
        "sortino",
        "max_drawdown",
        "win_rate",
        "profit_factor",
        "n_trades",
    ]
    summary: dict[str, Any] = {"n_folds": len(results), "folds": []}
    for k in keys:
        values = [float(r.metrics.get(k, 0.0)) for r in results]
        summary[f"{k}_mean"] = float(np.mean(values)) if values else 0.0
        summary[f"{k}_std"] = float(np.std(values)) if values else 0.0
        summary[f"{k}_min"] = float(np.min(values)) if values else 0.0
        summary[f"{k}_max"] = float(np.max(values)) if values else 0.0
    for r in results:
        summary["folds"].append(
            {"fold_index": r.fold_index, **_jsonable(r.metrics)}
        )
    return summary


# ===========================================================================
# Smoke test
# ===========================================================================


def _smoke_test() -> None:
    """Run an end-to-end smoke test with synthetic data.

    Generates 5,000 bars of synthetic NIFTY-style 5-min data, runs a dual-EMA
    crossover strategy, performs 3-fold walk-forward analysis, and writes a
    report to ``backtest/results/smoke/``.
    """
    logger.info("=== backtest.engine smoke test ===")
    cfg = BacktestConfig(
        initial_capital=1_000_000.0,
        symbol="NIFTY",
        commission_per_lot=50.0,
        slippage_bps=2.0,
        freq="5min",
        output_dir="backtest/results/smoke",
    )
    engine = BacktestEngine(cfg)
    df = generate_synthetic_data(n_bars=5000, start_price=18000.0, seed=42)
    engine.load_data(df)
    logger.info(f"Lot size for {cfg.symbol}: {cfg.lot_size()}")

    strategy = EMACrossStrategy(fast=9, slow=21)
    result = engine.run(strategy)

    logger.success(
        f"Single run — return={result.metrics['total_return']:+.2%} "
        f"sharpe={result.metrics['sharpe']:.2f} "
        f"DD={result.metrics['max_drawdown']:+.2%} "
        f"trades={int(result.metrics['n_trades'])}"
    )

    wfa = engine.walk_forward(strategy, n_splits=3)
    logger.success(f"Walk-forward complete: {len(wfa)} folds")

    engine.report(result, walk_forward_results=wfa)

    # Sanity-check Indian market helpers
    assert get_lot_size("NIFTY") == 25
    assert is_weekly_expiry(pd.Timestamp("2024-01-04"))  # a Thursday
    assert not is_weekly_expiry(pd.Timestamp("2024-01-05"))  # a Friday
    assert in_opening_range(pd.Timestamp("2024-01-02 09:05"))
    assert not in_opening_range(pd.Timestamp("2024-01-02 09:20"))
    assert in_square_off_window(pd.Timestamp("2024-01-02 15:20"))
    logger.success("Indian market helper sanity checks passed.")


if __name__ == "__main__":
    _smoke_test()
