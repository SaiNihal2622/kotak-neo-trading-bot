"""Event play: long straddle pre-event (RBI, Fed, Budget, monthly expiry)."""
from __future__ import annotations

from typing import Optional

from .base import BaseStrategy, SignalContext, StrategyName, TradePlan


class EventStraddleStrategy(BaseStrategy):
    """Buy ATM CE + ATM PE before a known event, hold through announcement."""
    name = StrategyName.EVENT_STRADDLE

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self.entry_minutes_before = self.config.get("entry_minutes_before", 30)
        self.exit_at_event = self.config.get("exit_at_event", True)

    def is_eligible(self, ctx: SignalContext, account_state: dict) -> tuple[bool, str]:
        if not ctx.upcoming_event:
            return False, "no upcoming event"
        if ctx.minutes_to_event is None or ctx.minutes_to_event > self.entry_minutes_before:
            return False, f"event too far ({ctx.minutes_to_event}m > {self.entry_minutes_before}m)"
        if ctx.minutes_to_event < 0:
            return False, "event already passed"
        return True, "eligible"

    def build_plan(self, ctx: SignalContext, account_state: dict) -> Optional[TradePlan]:
        eligible, reason = self.is_eligible(ctx, account_state)
        if not eligible:
            return None
        if not ctx.strikes:
            return None
        atm = min(ctx.strikes, key=lambda k: abs(k - ctx.spot))
        ce = ctx.option_ltps.get((atm, "CE"), 0.0)
        pe = ctx.option_ltps.get((atm, "PE"), 0.0)
        if min(ce, pe) <= 0:
            return None
        cost = ce + pe
        # target: 50% premium expansion, stop: 30% loss
        target = cost * 0.5
        stop = cost * 0.3
        return TradePlan(
            strategy=self.name,
            underlying=ctx.symbol,
            legs=[
                {"side": "BUY", "qty": 1, "strike": atm, "opt_type": "CE", "order_type": "LIMIT", "price": ce, "tag": f"ev_{ctx.symbol}_ce"},
                {"side": "BUY", "qty": 1, "strike": atm, "opt_type": "PE", "order_type": "LIMIT", "price": pe, "tag": f"ev_{ctx.symbol}_pe"},
            ],
            target=target,
            stop=stop,
            confidence=0.6,
            reason=f"event straddle: {ctx.upcoming_event} in {ctx.minutes_to_event}m",
            expected_hold_minutes=self.entry_minutes_before,
        )
