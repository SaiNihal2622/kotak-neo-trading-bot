"""Technical analysis: indicators + candlestick patterns via pandas-ta."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd
from loguru import logger

# pandas_ta is an optional heavy dependency. Import lazily inside analyze() so
# that modules importing this file (e.g. via kotak_bot.__main__ -> build_broker
# in test_live_safety) don't fail at import time if the package is missing.
# The user gets a clear error only when technical analysis is actually invoked.
_ta = None


def _get_ta():
    """Lazy import of pandas_ta. Cached on first successful import."""
    global _ta
    if _ta is None:
        try:
            import pandas_ta as ta  # type: ignore
            _ta = ta
        except ImportError as e:
            raise ImportError(
                "pandas_ta is required for TechnicalAnalyzer.analyze(). "
                "Install it with: pip install pandas_ta"
            ) from e
    return _ta


@dataclass
class TechnicalSignal:
    symbol: str
    side: str  # 'BUY' (CE), 'SELL' (PE), or 'NEUTRAL'
    confidence: float  # 0..1
    reason: str
    rsi: float = 0.0
    adx: float = 0.0
    ema_fast: float = 0.0
    ema_slow: float = 0.0
    atr: float = 0.0
    macd_hist: float = 0.0
    pattern: str = ""
    supertrend: str = ""  # 'up' / 'down' / 'none'


class TechnicalAnalyzer:
    """Computes indicators on a OHLCV dataframe and emits TechnicalSignal."""

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.ema_fast = self.config.get("ema_fast", 9)
        self.ema_slow = self.config.get("ema_slow", 21)
        self.rsi_period = self.config.get("rsi_period", 14)
        self.atr_period = self.config.get("atr_period", 14)
        self.adx_period = 14

    def analyze(self, df: pd.DataFrame, symbol: str = "NIFTY") -> TechnicalSignal:
        """Given an OHLCV dataframe, return a TechnicalSignal.

        df must have columns: open, high, low, close, volume (datetime index optional).
        """
        if df is None or df.empty or len(df) < max(self.ema_slow, self.rsi_period) + 5:
            return TechnicalSignal(symbol=symbol, side="NEUTRAL", confidence=0.0, reason="insufficient data")

        try:
            close = df["close"]
            high = df["high"]
            low = df["low"]
            vol = df["volume"] if "volume" in df.columns else None

            # Lazy import pandas_ta — fail with a clear error if it's not installed.
            ta = _get_ta()

            # core indicators
            rsi_s = ta.rsi(close, length=self.rsi_period)
            adx_s = ta.adx(high, low, close, length=self.adx_period)
            macd_s = ta.macd(close, fast=12, slow=26, signal=9)
            st_s = ta.supertrend(high, low, close, length=10, multiplier=3.0)
            atr_s = ta.atr(high, low, close, length=self.atr_period)
            ema_f = ta.ema(close, length=self.ema_fast)
            ema_s_l = ta.ema(close, length=self.ema_slow)

            # candle patterns (lightweight subset)
            try:
                patterns = []
                for pat in ("engulfing", "hammer", "shootingstar", "morningstar", "eveningstar", "doji"):
                    s = getattr(ta, pat, None)
                    if s is not None:
                        patterns.append(s(df))
                # combine latest non-zero pattern
                latest_pattern = ""
                if patterns:
                    p_df = pd.concat(patterns, axis=1)
                    last = p_df.iloc[-1]
                    if last.abs().max() > 0:
                        latest_pattern = p_df.columns[last.abs().argmax()].split("_")[-1]
            except Exception as e:
                logger.debug(f"pattern calc: {e}")
                latest_pattern = ""

            # extract latest values
            rsi = float(rsi_s.iloc[-1]) if rsi_s is not None and not rsi_s.empty else 50.0
            adx = float(adx_s.iloc[-1].iloc[0]) if adx_s is not None and not adx_s.empty else 0.0
            adx = adx if not pd.isna(adx) else 0.0
            macd_hist = 0.0
            if macd_s is not None and not macd_s.empty:
                macd_hist = float(macd_s.iloc[-1].iloc[-1]) if hasattr(macd_s.iloc[-1], 'iloc') else float(list(macd_s.iloc[-1])[-1])
            ema_f_val = float(ema_f.iloc[-1]) if ema_f is not None and not ema_f.empty else 0.0
            ema_s_val = float(ema_s_l.iloc[-1]) if ema_s_l is not None and not ema_s_l.empty else 0.0
            atr_val = float(atr_s.iloc[-1]) if atr_s is not None and not atr_s.empty else 0.0
            st_dir = ""
            if st_s is not None and not st_s.empty:
                # supertrend returns a df with a column like 'SUPERT_10_3.0' + 'SUPERTd_10_3.0'
                for col in st_s.columns:
                    if col.startswith("SUPERTd"):
                        st_dir = "up" if st_s[col].iloc[-1] > 0 else "down"
                        break

            # score-based signal
            score = 0.0
            reasons = []
            # EMA cross
            if ema_f_val > ema_s_val:
                score += 0.25
                reasons.append("ema_bull_cross")
            elif ema_f_val < ema_s_val:
                score -= 0.25
                reasons.append("ema_bear_cross")
            # RSI
            if rsi < 35:
                score += 0.25
                reasons.append("rsi_oversold")
            elif rsi > 65:
                score -= 0.25
                reasons.append("rsi_overbought")
            # MACD
            if macd_hist > 0:
                score += 0.2
                reasons.append("macd_positive")
            elif macd_hist < 0:
                score -= 0.2
                reasons.append("macd_negative")
            # Supertrend
            if st_dir == "up":
                score += 0.2
                reasons.append("supertrend_up")
            elif st_dir == "down":
                score -= 0.2
                reasons.append("supertrend_down")
            # ADX strength multiplier
            adx_mult = min(1.5, max(0.5, adx / 25.0))
            score *= adx_mult
            # Pattern bonus
            if latest_pattern in ("bullish", "hammer", "morningstar", "engulfing"):
                score += 0.1
            elif latest_pattern in ("bearish", "shootingstar", "eveningstar"):
                score -= 0.1

            # decide
            side = "NEUTRAL"
            if score > 0.3:
                side = "BUY"  # buy CE
            elif score < -0.3:
                side = "SELL"  # buy PE
            confidence = min(1.0, abs(score))

            return TechnicalSignal(
                symbol=symbol,
                side=side,
                confidence=confidence,
                reason=", ".join(reasons) or "no signal",
                rsi=rsi, adx=adx,
                ema_fast=ema_f_val, ema_slow=ema_s_val,
                atr=atr_val, macd_hist=macd_hist,
                pattern=latest_pattern,
                supertrend=st_dir,
            )
        except Exception as e:
            logger.exception(f"TechnicalAnalyzer.analyze failed: {e}")
            return TechnicalSignal(symbol=symbol, side="NEUTRAL", confidence=0.0, reason=f"error: {e}")
