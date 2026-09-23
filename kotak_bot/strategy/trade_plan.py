"""Backwards-compat shim for `from kotak_bot.strategy.trade_plan import TradePlan`.

FIX 2026-09-23 10:48 — TradePlan/StrategyName were originally defined in this
file but got moved to base.py without updating the imports in __main__.py.
Rather than risk breaking other callers, this module re-exports from base.
"""
from kotak_bot.strategy.base import StrategyName, TradePlan

__all__ = ["StrategyName", "TradePlan"]
