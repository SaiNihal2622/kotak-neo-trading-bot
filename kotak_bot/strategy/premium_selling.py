"""Premium selling strategies: iron condor, short strangle.

For range-bound markets. Short premium with defined risk (spreads).
"""
from __future__ import annotations

from typing import Optional

from loguru import logger

from .base import BaseStrategy, SignalContext, StrategyName, TradePlan


class IronCondorStrategy(BaseStrategy):
    """Iron condor: OTM call spread + OTM put spread, same expiry."""
    name = StrategyName.IRON_CONDOR

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.wing_width = self.config.get("wing_width", 100)
        self.short_delta = self.config.get("short_delta", 0.16)
        self.profit_target_pct = self.config.get("profit_target_pct", 50)
        self.stop_loss_multiplier = self.config.get("stop_loss_multiplier", 2.0)

    def is_eligible(self, ctx: SignalContext, account_state: dict) -> tuple[bool, str]:
        if ctx.regime not in ("range",):
            return False, f"regime={ctx.regime} not range"
        if ctx.iv_rank < 40:
            return False, f"iv_rank={ctx.iv_rank:.0f} < 40 (premiums too low)"
        if ctx.vix > 18:
            return False, f"vix={ctx.vix:.1f} > 18 (too volatile)"
        return True, "eligible"

    def build_plan(self, ctx: SignalContext, account_state: dict) -> Optional[TradePlan]:
        eligible, reason = self.is_eligible(ctx, account_state)
        if not eligible:
            return None
        if not ctx.strikes or len(ctx.strikes) < 5:
            return None
        atm = min(ctx.strikes, key=lambda k: abs(k - ctx.spot))
        step = ctx.strikes[1] - ctx.strikes[0] if len(ctx.strikes) > 1 else 50
        # short strikes: ATM + wing
        short_ce = atm + self.wing_width
        short_pe = atm - self.wing_width
        long_ce = short_ce + self.wing_width
        long_pe = short_pe - self.wing_width
        # net credit = short_ce_premium + short_pe_premium - long_ce_premium - long_pe_premium
        sc = ctx.option_ltps.get((short_ce, "CE"), 0.0)
        sp = ctx.option_ltps.get((short_pe, "PE"), 0.0)
        lc = ctx.option_ltps.get((long_ce, "CE"), 0.0)
        lp = ctx.option_ltps.get((long_pe, "PE"), 0.0)
        if min(sc, sp, lc, lp) <= 0:
            return None
        net_credit = (sc + sp) - (lc + lp)
        max_loss = self.wing_width - net_credit
        if max_loss <= 0 or net_credit <= 0:
            return None
        return TradePlan(
            strategy=self.name,
            underlying=ctx.symbol,
            legs=[
                {"side": "SELL", "qty": 1, "strike": short_ce, "opt_type": "CE", "order_type": "LIMIT", "price": sc, "tag": f"ic_{ctx.symbol}_sc"},
                {"side": "BUY",  "qty": 1, "strike": long_ce,  "opt_type": "CE", "order_type": "LIMIT", "price": lc, "tag": f"ic_{ctx.symbol}_lc"},
                {"side": "SELL", "qty": 1, "strike": short_pe, "opt_type": "PE", "order_type": "LIMIT", "price": sp, "tag": f"ic_{ctx.symbol}_sp"},
                {"side": "BUY",  "qty": 1, "strike": long_pe,  "opt_type": "PE", "order_type": "LIMIT", "price": lp, "tag": f"ic_{ctx.symbol}_lp"},
            ],
            target=net_credit * (self.profit_target_pct / 100.0),
            stop=max_loss * self.stop_loss_multiplier,
            confidence=0.6,
            reason=f"iron condor: range regime, iv_rank={ctx.iv_rank:.0f}, credit={net_credit:.2f}",
            expected_hold_minutes=240,
        )


class ShortStrangleStrategy(BaseStrategy):
    """Short strangle: sell OTM CE + PE, no hedge (undefined risk — only for high-confidence range)."""
    name = StrategyName.SHORT_STRANGLE

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.short_delta = self.config.get("short_delta", 0.20)
        self.profit_target_pct = self.config.get("profit_target_pct", 50)
        self.stop_loss_multiplier = self.config.get("stop_loss_multiplier", 2.0)

    def is_eligible(self, ctx: SignalContext, account_state: dict) -> tuple[bool, str]:
        if ctx.regime != "range":
            return False, f"regime={ctx.regime} not range"
        if ctx.iv_rank < 50:
            return False, f"iv_rank={ctx.iv_rank:.0f} < 50"
        return True, "eligible"

    def build_plan(self, ctx: SignalContext, account_state: dict) -> Optional[TradePlan]:
        eligible, reason = self.is_eligible(ctx, account_state)
        if not eligible:
            return None
        if not ctx.strikes:
            return None
        atm = min(ctx.strikes, key=lambda k: abs(k - ctx.spot))
        step = ctx.strikes[1] - ctx.strikes[0] if len(ctx.strikes) > 1 else 50
        # OTM short strikes
        sc_strike = atm + step * 2
        sp_strike = atm - step * 2
        sc = ctx.option_ltps.get((sc_strike, "CE"), 0.0)
        sp = ctx.option_ltps.get((sp_strike, "PE"), 0.0)
        if min(sc, sp) <= 0:
            return None
        net_credit = sc + sp
        # conservative stop: 2x credit (since undefined risk)
        stop = net_credit * 2.0
        return TradePlan(
            strategy=self.name,
            underlying=ctx.symbol,
            legs=[
                {"side": "SELL", "qty": 1, "strike": sc_strike, "opt_type": "CE", "order_type": "LIMIT", "price": sc, "tag": f"ss_{ctx.symbol}_sc"},
                {"side": "SELL", "qty": 1, "strike": sp_strike, "opt_type": "PE", "order_type": "LIMIT", "price": sp, "tag": f"ss_{ctx.symbol}_sp"},
            ],
            target=net_credit * (self.profit_target_pct / 100.0),
            stop=stop,
            confidence=0.5,
            reason=f"short strangle: range + high IV",
            expected_hold_minutes=180,
        )
