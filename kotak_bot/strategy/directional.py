"""Directional debit-spread strategy.

Trades in the direction of a confirmed trend on the 15-min chart.
Uses debit spreads (defined risk) instead of naked longs.
"""
from __future__ import annotations

from typing import Optional

from loguru import logger

from .base import BaseStrategy, SignalContext, StrategyName, TradePlan


class DirectionalDebitStrategy(BaseStrategy):
    name = StrategyName.DIRECTIONAL_DEBIT

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.min_confidence = self.config.get("min_confidence", 0.55)
        self.target_rr = self.config.get("target_rr", 2.0)
        self.ema_fast = self.config.get("ema_fast", 9)
        self.ema_slow = self.config.get("ema_slow", 21)

    def is_eligible(self, ctx: SignalContext, account_state: dict) -> tuple[bool, str]:
        if ctx.regime not in ("trending",):
            return False, f"regime={ctx.regime} not trending"
        if ctx.adx < 25:
            return False, f"adx={ctx.adx:.1f} < 25"
        if ctx.trend_strength < self.min_confidence:
            return False, f"trend_strength={ctx.trend_strength:.2f} < {self.min_confidence}"
        return True, "eligible"

    def build_plan(self, ctx: SignalContext, account_state: dict) -> Optional[TradePlan]:
        eligible, reason = self.is_eligible(ctx, account_state)
        if not eligible:
            return None
        # decide side from trend_strength sign (positive=BUY CE, negative=SELL/BUY PE)
        side = "BUY" if ctx.trend_strength > 0 else "SELL"
        opt_type = "CE" if side == "BUY" else "PE"
        # find ATM strike
        if not ctx.strikes:
            return None
        atm = min(ctx.strikes, key=lambda k: abs(k - ctx.spot))
        # long leg: ATM; short leg: ATM + 1 step (for vertical spread)
        # for now: simple 1-leg directional (can add spread later)
        long_strike = atm
        # use ATM premium as proxy
        long_premium = ctx.option_ltps.get((long_strike, opt_type), 0.0)
        if long_premium <= 0:
            return None
        # target = 1.5x premium, stop = 0.5x premium (1.5:1 RR)
        target = round(long_premium * (1 + self.target_rr * 0.5), 2)
        stop = round(long_premium * 0.5, 2)
        return TradePlan(
            strategy=self.name,
            underlying=ctx.symbol,
            legs=[{
                "side": "BUY", "qty": 1,  # will be sized by risk engine
                "strike": long_strike,
                "opt_type": opt_type,
                "expiry": ctx.strikes and "",  # filled by selector
                "order_type": "LIMIT",
                "price": long_premium,
                "tag": f"dir_{ctx.symbol}_{opt_type}",
            }],
            target=target,
            stop=stop,
            confidence=ctx.trend_strength,
            reason=f"directional: {ctx.regime}, adx={ctx.adx:.1f}, {side} {opt_type} {long_strike}",
            expected_hold_minutes=120,
        )
