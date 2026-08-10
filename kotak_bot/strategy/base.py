"""Base strategy class."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class StrategyName(str, Enum):
    DIRECTIONAL_DEBIT = "directional_debit"
    IRON_CONDOR = "iron_condor"
    SHORT_STRANGLE = "short_strangle"
    EVENT_STRADDLE = "event_straddle"


@dataclass
class SignalContext:
    """All info a strategy needs to make a decision."""
    symbol: str           # underlying: "NIFTY" or "BANKNIFTY"
    spot: float           # current spot price
    vix: float
    iv_rank: float
    adx: float
    trend_strength: float
    regime: str           # 'trending' | 'range' | 'volatile'
    timestamp: datetime
    # option chain
    strikes: list[float] = field(default_factory=list)
    option_ltps: dict = field(default_factory=dict)  # (strike, opt_type) -> ltp
    option_ivs: dict = field(default_factory=dict)
    # event context
    upcoming_event: Optional[str] = None  # 'rbi_policy', 'us_fed', etc.
    minutes_to_event: Optional[int] = None
    # sentiment
    news_sentiment: float = 0.0  # -1..+1
    news_urgency: float = 0.0    # 0..1


@dataclass
class TradePlan:
    """A concrete plan to place a trade. The execution layer turns this into orders."""
    strategy: StrategyName
    underlying: str
    legs: list[dict]  # each leg: {side, qty, symbol, strike, opt_type, expiry, order_type, price, tag}
    target: float      # expected profit at target
    stop: float        # max loss
    confidence: float  # 0..1
    reason: str
    expiry: str = ""
    expected_hold_minutes: int = 60

    @property
    def is_multi_leg(self) -> bool:
        return len(self.legs) > 1

    @property
    def max_loss(self) -> float:
        return abs(self.stop)

    @property
    def max_profit(self) -> float:
        return abs(self.target)


class BaseStrategy(ABC):
    name: StrategyName

    @abstractmethod
    def is_eligible(self, ctx: SignalContext, account_state: dict) -> tuple[bool, str]: ...

    @abstractmethod
    def build_plan(self, ctx: SignalContext, account_state: dict) -> Optional[TradePlan]: ...
