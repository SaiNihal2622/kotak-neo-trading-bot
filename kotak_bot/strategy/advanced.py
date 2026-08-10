"""Advanced option strategies: vertical spreads, butterflies, calendars, jade lizard, long options.

Each strategy is a regime-preferred play. The StrategySelector picks the best one for
the current regime + signal context.
"""
from __future__ import annotations

import math
from typing import Optional

from loguru import logger

from .base import BaseStrategy, SignalContext, StrategyName, TradePlan


# =============================================================
# Bull Call Vertical (call debit spread) — bullish, defined risk
# =============================================================
class BullCallVerticalStrategy(BaseStrategy):
    name = StrategyName.DIRECTIONAL_DEBIT  # reuse enum value
    label = "bull_call_vertical"

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.wing_width = self.config.get("wing_width", 100)
        self.target_rr = self.config.get("target_rr", 2.0)
        self.min_confidence = self.config.get("min_confidence", 0.55)

    def is_eligible(self, ctx, account_state):
        # Trending up, momentum positive, news supportive
        if ctx.adx < 20:
            return False, f"adx={ctx.adx:.1f} < 20 (no trend)"
        if ctx.trend_strength <= 0:
            return False, f"trend_strength={ctx.trend_strength:.2f} not bullish"
        if ctx.news_sentiment < -0.3:
            return False, f"news sentiment {ctx.news_sentiment:.2f} bearish"
        if abs(ctx.trend_strength) < self.min_confidence:
            return False, f"trend_strength={ctx.trend_strength:.2f} < {self.min_confidence}"
        return True, "eligible: bullish trend"

    def build_plan(self, ctx, account_state):
        eligible, reason = self.is_eligible(ctx, account_state)
        if not eligible or not ctx.strikes:
            return None
        atm = min(ctx.strikes, key=lambda k: abs(k - ctx.spot))
        step = ctx.strikes[1] - ctx.strikes[0] if len(ctx.strikes) > 1 else 50
        long_strike = atm
        short_strike = atm + self.wing_width
        long_prem = ctx.option_ltps.get((long_strike, "CE"), 0.0)
        short_prem = ctx.option_ltps.get((short_strike, "CE"), 0.0)
        if min(long_prem, short_prem) <= 0:
            return None
        debit = long_prem - short_prem
        if debit <= 0:
            return None
        max_profit = self.wing_width - debit
        target = round(debit + (max_profit * 0.5), 2)
        stop = round(debit * 0.5, 2)
        return TradePlan(
            strategy=self.name,
            underlying=ctx.symbol,
            legs=[
                {"side": "BUY",  "qty": 1, "strike": long_strike,  "opt_type": "CE", "order_type": "LIMIT", "price": long_prem,  "tag": f"bcv_{ctx.symbol}_long"},
                {"side": "SELL", "qty": 1, "strike": short_strike, "opt_type": "CE", "order_type": "LIMIT", "price": short_prem, "tag": f"bcv_{ctx.symbol}_short"},
            ],
            target=target,
            stop=stop,
            confidence=min(0.9, abs(ctx.trend_strength)),
            reason=f"bull call vertical: adx={ctx.adx:.1f}, mom={ctx.trend_strength:+.2f}, debit={debit:.2f}",
            expected_hold_minutes=120,
        )


# =============================================================
# Bear Put Vertical (put debit spread) — bearish, defined risk
# =============================================================
class BearPutVerticalStrategy(BaseStrategy):
    name = StrategyName.DIRECTIONAL_DEBIT
    label = "bear_put_vertical"

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.wing_width = self.config.get("wing_width", 100)
        self.target_rr = self.config.get("target_rr", 2.0)
        self.min_confidence = self.config.get("min_confidence", 0.55)

    def is_eligible(self, ctx, account_state):
        if ctx.adx < 20:
            return False, f"adx={ctx.adx:.1f} < 20"
        if ctx.trend_strength >= 0:
            return False, f"trend_strength={ctx.trend_strength:.2f} not bearish"
        if ctx.news_sentiment > 0.3:
            return False, f"news sentiment {ctx.news_sentiment:.2f} bullish"
        if abs(ctx.trend_strength) < self.min_confidence:
            return False, f"|trend_strength|={abs(ctx.trend_strength):.2f} < {self.min_confidence}"
        return True, "eligible: bearish trend"

    def build_plan(self, ctx, account_state):
        eligible, reason = self.is_eligible(ctx, account_state)
        if not eligible or not ctx.strikes:
            return None
        atm = min(ctx.strikes, key=lambda k: abs(k - ctx.spot))
        step = ctx.strikes[1] - ctx.strikes[0] if len(ctx.strikes) > 1 else 50
        long_strike = atm
        short_strike = atm - self.wing_width
        long_prem = ctx.option_ltps.get((long_strike, "PE"), 0.0)
        short_prem = ctx.option_ltps.get((short_strike, "PE"), 0.0)
        if min(long_prem, short_prem) <= 0:
            return None
        debit = long_prem - short_prem
        if debit <= 0:
            return None
        max_profit = self.wing_width - debit
        target = round(debit + (max_profit * 0.5), 2)
        stop = round(debit * 0.5, 2)
        return TradePlan(
            strategy=self.name,
            underlying=ctx.symbol,
            legs=[
                {"side": "BUY",  "qty": 1, "strike": long_strike,  "opt_type": "PE", "order_type": "LIMIT", "price": long_prem,  "tag": f"bpv_{ctx.symbol}_long"},
                {"side": "SELL", "qty": 1, "strike": short_strike, "opt_type": "PE", "order_type": "LIMIT", "price": short_prem, "tag": f"bpv_{ctx.symbol}_short"},
            ],
            target=target,
            stop=stop,
            confidence=min(0.9, abs(ctx.trend_strength)),
            reason=f"bear put vertical: adx={ctx.adx:.1f}, mom={ctx.trend_strength:+.2f}, debit={debit:.2f}",
            expected_hold_minutes=120,
        )


# =============================================================
# Iron Butterfly — range, ATM-anchored, max prob
# =============================================================
class IronButterflyStrategy(BaseStrategy):
    name = StrategyName.IRON_CONDOR  # reuse
    label = "iron_butterfly"

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.wing_width = self.config.get("wing_width", 100)
        self.profit_target_pct = self.config.get("profit_target_pct", 50)
        self.stop_loss_multiplier = self.config.get("stop_loss_multiplier", 1.5)

    def is_eligible(self, ctx, account_state):
        if ctx.regime != "range":
            return False, f"regime={ctx.regime} not range"
        if ctx.iv_rank < 35:
            return False, f"iv_rank={ctx.iv_rank:.0f} < 35"
        if ctx.vix > 18:
            return False, f"vix={ctx.vix:.1f} too high"
        return True, "eligible: ATM-anchored range"

    def build_plan(self, ctx, account_state):
        eligible, reason = self.is_eligible(ctx, account_state)
        if not eligible or not ctx.strikes:
            return None
        atm = min(ctx.strikes, key=lambda k: abs(k - ctx.spot))
        # short ATM straddle
        sc = ctx.option_ltps.get((atm, "CE"), 0.0)
        sp = ctx.option_ltps.get((atm, "PE"), 0.0)
        # long protective wings
        lc = ctx.option_ltps.get((atm + self.wing_width, "CE"), 0.0)
        lp = ctx.option_ltps.get((atm - self.wing_width, "PE"), 0.0)
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
                {"side": "SELL", "qty": 1, "strike": atm, "opt_type": "CE", "order_type": "LIMIT", "price": sc, "tag": f"ib_{ctx.symbol}_sc"},
                {"side": "SELL", "qty": 1, "strike": atm, "opt_type": "PE", "order_type": "LIMIT", "price": sp, "tag": f"ib_{ctx.symbol}_sp"},
                {"side": "BUY",  "qty": 1, "strike": atm + self.wing_width, "opt_type": "CE", "order_type": "LIMIT", "price": lc, "tag": f"ib_{ctx.symbol}_lc"},
                {"side": "BUY",  "qty": 1, "strike": atm - self.wing_width, "opt_type": "PE", "order_type": "LIMIT", "price": lp, "tag": f"ib_{ctx.symbol}_lp"},
            ],
            target=net_credit * (self.profit_target_pct / 100.0),
            stop=max_loss * self.stop_loss_multiplier,
            confidence=0.65,
            reason=f"iron butterfly: ATM-anchored range, credit={net_credit:.2f}",
            expected_hold_minutes=240,
        )


# =============================================================
# Jade Lizard — short put + short call spread (high IV bullish/bearish)
# =============================================================
class JadeLizardStrategy(BaseStrategy):
    name = StrategyName.SHORT_STRANGLE  # reuse
    label = "jade_lizard"

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.wing_width = self.config.get("wing_width", 100)
        self.profit_target_pct = self.config.get("profit_target_pct", 50)
        self.stop_loss_multiplier = self.config.get("stop_loss_multiplier", 1.5)

    def is_eligible(self, ctx, account_state):
        if ctx.iv_rank < 45:
            return False, f"iv_rank={ctx.iv_rank:.0f} < 45"
        if ctx.regime not in ("range", "trending"):
            return False, f"regime={ctx.regime}"
        if ctx.vix > 20:
            return False, f"vix={ctx.vix:.1f} too high"
        return True, "eligible: high IV"

    def build_plan(self, ctx, account_state):
        eligible, reason = self.is_eligible(ctx, account_state)
        if not eligible or not ctx.strikes:
            return None
        atm = min(ctx.strikes, key=lambda k: abs(k - ctx.spot))
        # short put at ATM-1 step (or ATM-2 if wider)
        step = ctx.strikes[1] - ctx.strikes[0] if len(ctx.strikes) > 1 else 50
        sp_strike = atm - step
        sp = ctx.option_ltps.get((sp_strike, "PE"), 0.0)
        # short call + long call spread
        sc_strike = atm + step
        sc = ctx.option_ltps.get((sc_strike, "CE"), 0.0)
        lc_strike = sc_strike + self.wing_width
        lc = ctx.option_ltps.get((lc_strike, "CE"), 0.0)
        if min(sp, sc, lc) <= 0:
            return None
        net_credit = sp + sc - lc
        if net_credit <= 0:
            return None
        max_loss = self.wing_width - net_credit  # if call spread breached
        # the short put has undefined risk but capped by lot size
        return TradePlan(
            strategy=self.name,
            underlying=ctx.symbol,
            legs=[
                {"side": "SELL", "qty": 1, "strike": sp_strike, "opt_type": "PE", "order_type": "LIMIT", "price": sp, "tag": f"jl_{ctx.symbol}_sp"},
                {"side": "SELL", "qty": 1, "strike": sc_strike, "opt_type": "CE", "order_type": "LIMIT", "price": sc, "tag": f"jl_{ctx.symbol}_sc"},
                {"side": "BUY",  "qty": 1, "strike": lc_strike, "opt_type": "CE", "order_type": "LIMIT", "price": lc, "tag": f"jl_{ctx.symbol}_lc"},
            ],
            target=net_credit * (self.profit_target_pct / 100.0),
            stop=max_loss * self.stop_loss_multiplier,
            confidence=0.6,
            reason=f"jade lizard: high IV, credit={net_credit:.2f}",
            expected_hold_minutes=300,
        )


# =============================================================
# Long Straddle — event play / pre-news / high volatility
# =============================================================
class LongStraddleStrategy(BaseStrategy):
    name = StrategyName.EVENT_STRADDLE  # reuse
    label = "long_straddle"

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.target_rr = self.config.get("target_rr", 1.5)
        self.stop_loss_multiplier = self.config.get("stop_loss_multiplier", 1.0)

    def is_eligible(self, ctx, account_state):
        if ctx.regime not in ("volatile", "trending"):
            return False, f"regime={ctx.regime} (want volatile)"
        if ctx.iv_rank < 25:
            return False, f"iv_rank={ctx.iv_rank:.0f} < 25 (premiums too cheap)"
        if ctx.news_urgency < 0.4:
            return False, f"news_urgency={ctx.news_urgency:.2f} < 0.4 (no catalyst)"
        return True, "eligible: volatile + catalyst"

    def build_plan(self, ctx, account_state):
        eligible, reason = self.is_eligible(ctx, account_state)
        if not eligible or not ctx.strikes:
            return None
        atm = min(ctx.strikes, key=lambda k: abs(k - ctx.spot))
        sc = ctx.option_ltps.get((atm, "CE"), 0.0)
        sp = ctx.option_ltps.get((atm, "PE"), 0.0)
        if min(sc, sp) <= 0:
            return None
        debit = sc + sp
        # target: 1.5x debit move in either direction
        target = round(debit * (1 + self.target_rr * 0.5), 2)
        stop = round(debit * self.stop_loss_multiplier, 2)
        return TradePlan(
            strategy=self.name,
            underlying=ctx.symbol,
            legs=[
                {"side": "BUY", "qty": 1, "strike": atm, "opt_type": "CE", "order_type": "LIMIT", "price": sc, "tag": f"ls_{ctx.symbol}_c"},
                {"side": "BUY", "qty": 1, "strike": atm, "opt_type": "PE", "order_type": "LIMIT", "price": sp, "tag": f"ls_{ctx.symbol}_p"},
            ],
            target=target,
            stop=stop,
            confidence=0.55,
            reason=f"long straddle: volatile + catalyst, debit={debit:.2f}",
            expected_hold_minutes=90,
        )


# =============================================================
# Calendar Spread — sell near, buy far, time decay edge in range
# =============================================================
class CalendarSpreadStrategy(BaseStrategy):
    name = StrategyName.IRON_CONDOR  # reuse multi-leg container
    label = "calendar"

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.profit_target_pct = self.config.get("profit_target_pct", 40)
        self.stop_loss_multiplier = self.config.get("stop_loss_multiplier", 1.5)

    def is_eligible(self, ctx, account_state):
        if ctx.regime != "range":
            return False, f"regime={ctx.regime} not range"
        if ctx.iv_rank < 30:
            return False, f"iv_rank={ctx.iv_rank:.0f} < 30"
        # Calendar needs both expiries — we approximate with same expiry for paper
        return True, "eligible: range (calendar proxy)"

    def build_plan(self, ctx, account_state):
        eligible, reason = self.is_eligible(ctx, account_state)
        if not eligible or not ctx.strikes:
            return None
        atm = min(ctx.strikes, key=lambda k: abs(k - ctx.spot))
        # Calendar proxy: short near ATM, long next OTM (different strikes)
        # For paper mode with single-expiry universe, this is a debit diagonal
        step = ctx.strikes[1] - ctx.strikes[0] if len(ctx.strikes) > 1 else 50
        sc_strike = atm
        lc_strike = atm + step
        sc = ctx.option_ltps.get((sc_strike, "CE"), 0.0)
        lc = ctx.option_ltps.get((lc_strike, "CE"), 0.0)
        if min(sc, lc) <= 0:
            return None
        # net debit (we want cheap here)
        net_debit = lc - sc
        if net_debit <= 0:
            return None
        # target: 40% of debit, stop: 1.5x debit
        target = round(net_debit * (1 + self.profit_target_pct / 100.0), 2)
        stop = round(net_debit * self.stop_loss_multiplier, 2)
        return TradePlan(
            strategy=self.name,
            underlying=ctx.symbol,
            legs=[
                {"side": "SELL", "qty": 1, "strike": sc_strike, "opt_type": "CE", "order_type": "LIMIT", "price": sc, "tag": f"cal_{ctx.symbol}_sc"},
                {"side": "BUY",  "qty": 1, "strike": lc_strike, "opt_type": "CE", "order_type": "LIMIT", "price": lc, "tag": f"cal_{ctx.symbol}_lc"},
            ],
            target=target,
            stop=stop,
            confidence=0.5,
            reason=f"calendar proxy: range, debit={net_debit:.2f}",
            expected_hold_minutes=300,
        )


# =============================================================
# Long Call — single-leg directional (momentum play)
# =============================================================
class LongCallStrategy(BaseStrategy):
    name = StrategyName.DIRECTIONAL_DEBIT
    label = "long_call"

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.target_rr = self.config.get("target_rr", 2.0)

    def is_eligible(self, ctx, account_state):
        if ctx.adx < 25:
            return False, f"adx={ctx.adx:.1f} < 25"
        if ctx.trend_strength <= 0:
            return False, "not bullish"
        if abs(ctx.trend_strength) < 0.6:
            return False, f"|mom|={abs(ctx.trend_strength):.2f} < 0.6 (weak trend)"
        return True, "eligible: strong uptrend"

    def build_plan(self, ctx, account_state):
        eligible, reason = self.is_eligible(ctx, account_state)
        if not eligible or not ctx.strikes:
            return None
        atm = min(ctx.strikes, key=lambda k: abs(k - ctx.spot))
        prem = ctx.option_ltps.get((atm, "CE"), 0.0)
        if prem <= 0:
            return None
        target = round(prem * (1 + self.target_rr * 0.5), 2)
        stop = round(prem * 0.5, 2)
        return TradePlan(
            strategy=self.name,
            underlying=ctx.symbol,
            legs=[
                {"side": "BUY", "qty": 1, "strike": atm, "opt_type": "CE", "order_type": "LIMIT", "price": prem, "tag": f"lc_{ctx.symbol}"},
            ],
            target=target,
            stop=stop,
            confidence=min(0.9, abs(ctx.trend_strength)),
            reason=f"long call: adx={ctx.adx:.1f}, mom={ctx.trend_strength:+.2f}",
            expected_hold_minutes=90,
        )


# =============================================================
# Long Put — single-leg directional (momentum play)
# =============================================================
class LongPutStrategy(BaseStrategy):
    name = StrategyName.DIRECTIONAL_DEBIT
    label = "long_put"

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.target_rr = self.config.get("target_rr", 2.0)

    def is_eligible(self, ctx, account_state):
        if ctx.adx < 25:
            return False, f"adx={ctx.adx:.1f} < 25"
        if ctx.trend_strength >= 0:
            return False, "not bearish"
        if abs(ctx.trend_strength) < 0.6:
            return False, f"|mom|={abs(ctx.trend_strength):.2f} < 0.6"
        return True, "eligible: strong downtrend"

    def build_plan(self, ctx, account_state):
        eligible, reason = self.is_eligible(ctx, account_state)
        if not eligible or not ctx.strikes:
            return None
        atm = min(ctx.strikes, key=lambda k: abs(k - ctx.spot))
        prem = ctx.option_ltps.get((atm, "PE"), 0.0)
        if prem <= 0:
            return None
        target = round(prem * (1 + self.target_rr * 0.5), 2)
        stop = round(prem * 0.5, 2)
        return TradePlan(
            strategy=self.name,
            underlying=ctx.symbol,
            legs=[
                {"side": "BUY", "qty": 1, "strike": atm, "opt_type": "PE", "order_type": "LIMIT", "price": prem, "tag": f"lp_{ctx.symbol}"},
            ],
            target=target,
            stop=stop,
            confidence=min(0.9, abs(ctx.trend_strength)),
            reason=f"long put: adx={ctx.adx:.1f}, mom={ctx.trend_strength:+.2f}",
            expected_hold_minutes=90,
        )
