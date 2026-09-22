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
        # FIX 2026-09-22 15:45: realistic limit-price tolerance. If bid is unavailable
        # we allow up to this fraction of LTP for SELL limits (vs 0% before — which
        # meant any LTP > bid would reject). 0.05 = 5% LTP buffer (vs old "0%" = instant
        # reject). For BUY limits we tolerate limit = ask * (1 + buffer).
        self.limit_tolerance_pct = float(self.config.get("limit_tolerance_pct", 5.0))

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
        # FIX 2026-09-22 15:45: realistic limit pricing.
        # For SELL wings, use bid (or LTP * (1 - tolerance) if bid unavailable).
        # For BUY wings, use ask (or LTP * (1 + tolerance) if ask unavailable).
        # This is the realistic-mode contract: a SELL fills at the bid (or limit,
        # whichever is higher), so limit must be <= bid. A BUY fills at ask (or
        # limit, whichever is lower), so limit must be >= ask. Using LTP directly
        # caused the 2026-09-22 iron condor SELL rejections (limit=27.5 vs bid=10.5).
        tol = self.limit_tolerance_pct / 100.0
        sc_bid = ctx.option_bids.get((short_ce, "CE"), 0.0)
        sp_bid = ctx.option_bids.get((short_pe, "PE"), 0.0)
        lc_ask = ctx.option_asks.get((long_ce, "CE"), 0.0)
        lp_ask = ctx.option_asks.get((long_pe, "PE"), 0.0)
        # SELL limit = bid (with small discount to ensure fill) — only if bid is known
        # Otherwise fall back to LTP * (1 - tolerance) which is safer than LTP itself
        sc_limit = sc_bid if sc_bid > 0 else sc * (1.0 - tol)
        sp_limit = sp_bid if sp_bid > 0 else sp * (1.0 - tol)
        # BUY limit = ask (or LTP * (1 + tolerance)) so the LIMIT can actually fill
        lc_limit = lc_ask if lc_ask > 0 else lc * (1.0 + tol)
        lp_limit = lp_ask if lp_ask > 0 else lp * (1.0 + tol)
        # Final safety: clamp to tick size to avoid alignment rejections later
        from kotak_bot.broker.paper_client import PaperClient
        sc_limit = PaperClient._align_to_tick(sc_limit)
        sp_limit = PaperClient._align_to_tick(sp_limit)
        lc_limit = PaperClient._align_to_tick(lc_limit)
        lp_limit = PaperClient._align_to_tick(lp_limit)
        net_credit = (sc + sp) - (lc + lp)
        max_loss = self.wing_width - net_credit
        if max_loss <= 0 or net_credit <= 0:
            return None
        return TradePlan(
            strategy=self.name,
            underlying=ctx.symbol,
            legs=[
                {"side": "SELL", "qty": 1, "strike": short_ce, "opt_type": "CE", "order_type": "LIMIT", "price": sc_limit, "tag": f"ic_{ctx.symbol}_sc"},
                {"side": "BUY",  "qty": 1, "strike": long_ce,  "opt_type": "CE", "order_type": "LIMIT", "price": lc_limit, "tag": f"ic_{ctx.symbol}_lc"},
                {"side": "SELL", "qty": 1, "strike": short_pe, "opt_type": "PE", "order_type": "LIMIT", "price": sp_limit, "tag": f"ic_{ctx.symbol}_sp"},
                {"side": "BUY",  "qty": 1, "strike": long_pe,  "opt_type": "PE", "order_type": "LIMIT", "price": lp_limit, "tag": f"ic_{ctx.symbol}_lp"},
            ],
            target=net_credit * (self.profit_target_pct / 100.0),
            stop=max_loss * self.stop_loss_multiplier,
            confidence=0.6,
            reason=(
                f"iron condor: range regime, iv_rank={ctx.iv_rank:.0f}, credit={net_credit:.2f}, "
                f"SELL @ bid (or LTP*{1-tol:.2f}), BUY @ ask (or LTP*{1+tol:.2f})"
            ),
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
