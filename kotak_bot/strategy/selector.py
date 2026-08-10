"""Regime + signal-based strategy selector.
Picks the BEST strategy for the current regime, signal strength, news context, and
recent performance. Maintains a multi-strategy library of 10 plays.
"""
from __future__ import annotations

from typing import Optional

from loguru import logger

from .base import BaseStrategy, SignalContext, StrategyName, TradePlan
from .directional import DirectionalDebitStrategy
from .event_play import EventStraddleStrategy
from .premium_selling import IronCondorStrategy, ShortStrangleStrategy
from .advanced import (
    BullCallVerticalStrategy,
    BearPutVerticalStrategy,
    IronButterflyStrategy,
    JadeLizardStrategy,
    LongStraddleStrategy,
    CalendarSpreadStrategy,
    LongCallStrategy,
    LongPutStrategy,
)


class StrategySelector:
    def __init__(self, config: dict | None = None):
        self.config = config or {}
        # Range-bound
        self.iron_condor = IronCondorStrategy(self.config.get("premium_selling", {}).get("iron_condor", {}))
        self.short_strangle = ShortStrangleStrategy(self.config.get("premium_selling", {}).get("strangle", {}))
        self.iron_butterfly = IronButterflyStrategy(self.config.get("iron_butterfly", {}))
        self.jade_lizard = JadeLizardStrategy(self.config.get("jade_lizard", {}))
        self.calendar = CalendarSpreadStrategy(self.config.get("calendar", {}))
        # Directional
        self.bull_call_vertical = BullCallVerticalStrategy(self.config.get("bull_call_vertical", {}))
        self.bear_put_vertical = BearPutVerticalStrategy(self.config.get("bear_put_vertical", {}))
        self.long_call = LongCallStrategy(self.config.get("long_call", {}))
        self.long_put = LongPutStrategy(self.config.get("long_put", {}))
        # Volatile / event
        self.long_straddle = LongStraddleStrategy(self.config.get("long_strangle", {}))  # reuse config block
        # Event play
        self.event_play = EventStraddleStrategy(self.config.get("event_play", {}))
        # Legacy
        self.directional = DirectionalDebitStrategy(self.config.get("directional", {}))

    def all_strategies(self) -> list[BaseStrategy]:
        return [
            # Range-bound (highest priority when regime=range)
            self.iron_condor,
            self.iron_butterfly,
            self.jade_lizard,
            self.short_strangle,
            self.calendar,
            # Directional (highest when regime=trending)
            self.bull_call_vertical,
            self.bear_put_vertical,
            self.long_call,
            self.long_put,
            # Volatile
            self.long_straddle,
            # Event
            self.event_play,
        ]

    def select(self, ctx: SignalContext, account_state: dict) -> Optional[TradePlan]:
        """Pick the best strategy. Strategy priority depends on regime:
        - Event imminent (< 30 min): event_straddle
        - Range regime: iron_condor > iron_butterfly > jade_lizard > strangle > calendar
        - Trending up: bull_call_vertical > long_call
        - Trending down: bear_put_vertical > long_put
        - Volatile: long_straddle
        """
        # 1) Event play takes priority
        if ctx.upcoming_event and ctx.minutes_to_event is not None and ctx.minutes_to_event <= 30:
            plan = self.event_play.build_plan(ctx, account_state)
            if plan:
                logger.info(f"Selected: {plan.strategy.value} — {plan.reason}")
                return plan

        # 2) Regime-based prioritization
        ordered: list[BaseStrategy] = []
        if ctx.regime == "range":
            ordered = [
                self.iron_condor, self.iron_butterfly, self.jade_lizard,
                self.short_strangle, self.calendar,
            ]
        elif ctx.regime == "trending":
            if ctx.trend_strength > 0:  # bullish
                ordered = [self.bull_call_vertical, self.long_call]
            else:  # bearish
                ordered = [self.bear_put_vertical, self.long_put]
        elif ctx.regime == "volatile":
            ordered = [self.long_straddle, self.jade_lizard]
        else:
            # unknown regime — try range plays first, then fallback
            ordered = [
                self.iron_condor, self.iron_butterfly, self.jade_lizard,
                self.short_strangle, self.bull_call_vertical, self.bear_put_vertical,
            ]

        # 3) Try each strategy in order
        for strat in ordered:
            eligible, reason = strat.is_eligible(ctx, account_state)
            if not eligible:
                logger.debug(f"Skip {getattr(strat, 'label', strat.name.value)}: {reason}")
                continue
            try:
                plan = strat.build_plan(ctx, account_state)
                if plan:
                    logger.info(f"Selected: {getattr(strat, 'label', strat.name.value)} — {plan.reason}")
                    return plan
            except Exception as e:
                logger.warning(f"build_plan failed for {getattr(strat, 'label', strat.name.value)}: {e}")
                continue

        logger.info(f"No strategy eligible for {ctx.symbol} (regime={ctx.regime}, adx={ctx.adx:.1f}, mom={ctx.trend_strength:+.2f}, iv_rank={ctx.iv_rank:.0f})")
        return None
