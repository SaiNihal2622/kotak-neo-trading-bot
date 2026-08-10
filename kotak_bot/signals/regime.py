"""Market regime detector.

Decides: TRENDING | RANGE | VOLATILE
Based on: ADX (trend strength), India VIX (vol), IV rank of options, market breadth.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import pandas as pd
from loguru import logger


class Regime(str, Enum):
    TRENDING = "trending"
    RANGE = "range"
    VOLATILE = "volatile"
    UNKNOWN = "unknown"


@dataclass
class RegimeState:
    regime: Regime
    confidence: float
    adx: float
    vix: float
    iv_rank: float
    reason: str


class RegimeDetector:
    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.adx_trend = self.config.get("adx_trending_threshold", 25)
        self.adx_range = self.config.get("adx_range_threshold", 20)
        self.vix_low = self.config.get("vix_low", 12)
        self.vix_high = self.config.get("vix_high", 18)
        self.iv_rank_low = self.config.get("iv_rank_low", 30)
        self.iv_rank_high = self.config.get("iv_rank_high", 70)

    def detect(self, df: pd.DataFrame, vix: float = 14.0, iv_rank: float = 50.0,
               momentum: float = 0.0, spot: float = 0.0, atm: float = 0.0) -> RegimeState:
        """Detect current regime.

        df: OHLCV of the underlying (NIFTY/BANKNIFTY), used for ADX.
        vix: latest India VIX (default 14 if unknown).
        iv_rank: 0-100 percentile of current IV vs 1y range (50 = neutral).
        momentum: % price change over recent tick window (used as ADX proxy when df is None).
        spot: current spot price.
        atm: ATM strike (for distance-from-ATM check).
        """
        adx = 0.0
        try:
            if df is not None and len(df) > 30:
                import pandas_ta as ta
                adx_s = ta.adx(df["high"], df["low"], df["close"], length=14)
                if adx_s is not None and not adx_s.empty:
                    adx = float(adx_s.iloc[-1].iloc[0])
                    if pd.isna(adx):
                        adx = 0.0
        except Exception as e:
            logger.debug(f"adx calc: {e}")

        # If no real ADX (df=None), derive a proxy from |momentum|
        # |momentum| of 0.5% over 10 sec ≈ mild trend; 1%+ = strong trend
        if df is None or adx == 0.0:
            adx_proxy = min(50.0, abs(momentum) * 5000)  # 0.5% → 25, 1% → 50
            if adx_proxy > 0:
                adx = max(adx, adx_proxy)
            logger.debug(f"regime: adx proxy from momentum={momentum:+.4f} → adx={adx:.1f}")

        # Decision tree
        regime = Regime.UNKNOWN
        reason = ""
        confidence = 0.5

        if vix > self.vix_high:
            # VIX high → volatile regardless of ADX
            regime = Regime.VOLATILE
            reason = f"vix={vix:.1f} > {self.vix_high}"
            confidence = min(0.95, 0.6 + (vix - self.vix_high) / 30)
        elif iv_rank > self.iv_rank_high and adx < self.adx_range:
            regime = Regime.VOLATILE
            reason = f"iv_rank={iv_rank:.0f} high + low adx={adx:.1f}"
            confidence = 0.7
        elif adx >= self.adx_trend:
            regime = Regime.TRENDING
            direction = "up" if momentum > 0 else "down"
            reason = f"adx={adx:.1f} >= {self.adx_trend} (mom={momentum:+.4f} → {direction})"
            confidence = min(0.95, 0.5 + (adx - self.adx_trend) / 50)
        elif adx <= self.adx_range and vix < self.vix_low:
            regime = Regime.RANGE
            reason = f"adx={adx:.1f} <= {self.adx_range}, vix={vix:.1f} low"
            confidence = 0.7
        else:
            # middle ground — default to range with lower confidence
            regime = Regime.RANGE
            reason = f"adx={adx:.1f}, vix={vix:.1f} — default range (mom={momentum:+.4f})"
            confidence = 0.4

        return RegimeState(
            regime=regime,
            confidence=confidence,
            adx=adx,
            vix=vix,
            iv_rank=iv_rank,
            reason=reason,
        )
