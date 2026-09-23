"""Strategy layer: directional, premium_selling, event_play, regime-based selector.

FIX 2026-09-23 10:48 — re-export TradePlan + StrategyName from base.py. Previously
`from kotak_bot.strategy.trade_plan import TradePlan, StrategyName` in
__main__.py raised `No module named 'kotak_bot.strategy.trade_plan'`, which
caused the bot to log `[QUANT-ACTION] register_external failed` every cycle
and lose the brain-driven trade registration with OrderManager — leading to
untracked positions that survive force-square. Now the symbols are exported
at the package root so both `from kotak_bot.strategy import TradePlan` and
`from kotak_bot.strategy.trade_plan import TradePlan` work.
"""
from kotak_bot.strategy.base import StrategyName, TradePlan, SignalContext

__all__ = [
    "StrategyName",
    "TradePlan",
    "SignalContext",
]
