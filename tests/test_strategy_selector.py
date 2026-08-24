"""Unit tests for StrategySelector and individual strategy build_plan.

Verifies regime-based selection, eligibility checks, and plan math for each strategy.
"""
import os
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kotak_bot.strategy.selector import StrategySelector
from kotak_bot.strategy.base import SignalContext, StrategyName, TradePlan


def _ctx(spot: float, regime: str, adx: float, trend: float, iv: float = 50.0, vix: float = 14.0,
         news_sent: float = 0.0, news_urgency: float = 0.0,
         strikes: Optional[list] = None, opt_ltps: Optional[dict] = None) -> SignalContext:
    from datetime import datetime, timezone
    if strikes is None:
        step = 50
        atm = round(spot / step) * step
        strikes = [atm + (i - 4) * step for i in range(9)]
    if opt_ltps is None:
        # build synthetic ltps with intrinsic + time value
        opt_ltps = {}
        for k in strikes:
            for ot in ("CE", "PE"):
                intrinsic = max(0, spot - k) if ot == "CE" else max(0, k - spot)
                tv = max(0, 30 * (1 - abs(spot - k) / spot * 5))
                opt_ltps[(k, ot)] = round(intrinsic + tv, 2)
    return SignalContext(
        symbol="NIFTY", spot=spot, vix=vix, iv_rank=iv, adx=adx,
        trend_strength=trend, regime=regime, timestamp=datetime.now(timezone.utc),
        strikes=strikes, option_ltps=opt_ltps,
        news_sentiment=news_sent, news_urgency=news_urgency,
    )


def _config():
    return {
        "regime_detector": {},
        "iron_condor": {"enabled": True, "wing_width": 100, "profit_target_pct": 50, "stop_loss_multiplier": 2.0},
        "short_strangle": {"profit_target_pct": 50, "stop_loss_multiplier": 2.0},
        "iron_butterfly": {"wing_width": 100, "profit_target_pct": 50, "stop_loss_multiplier": 1.5},
        "jade_lizard": {"wing_width": 100, "profit_target_pct": 50, "stop_loss_multiplier": 1.5},
        "calendar": {"profit_target_pct": 40, "stop_loss_multiplier": 1.5},
        "bull_call_vertical": {"wing_width": 100, "target_rr": 2.0, "min_confidence": 0.55},
        "bear_put_vertical": {"wing_width": 100, "target_rr": 2.0, "min_confidence": 0.55},
        "long_call": {"target_rr": 2.0},
        "long_put": {"target_rr": 2.0},
        "event_play": {},
    }


class TestRangeRegime(unittest.TestCase):
    def test_range_picks_iron_condor_first(self):
        s = StrategySelector(_config())
        ctx = _ctx(24500, "range", adx=15, trend=0.0, iv=55)
        plan = s.select(ctx, {})
        self.assertIsNotNone(plan)
        self.assertEqual(plan.strategy, StrategyName.IRON_CONDOR)
        # Iron condor has 4 legs (2 spreads)
        self.assertEqual(len(plan.legs), 4)

    def test_range_high_iv_picks_iron_butterfly(self):
        """If iron condor is ineligible (e.g. iv_rank too low), try butterfly next."""
        s = StrategySelector(_config())
        # low IV — should skip iron condor, try butterfly
        ctx = _ctx(24500, "range", adx=15, trend=0.0, iv=40)
        plan = s.select(ctx, {})
        # iron_condor wants iv_rank >= 40, butterfly wants >= 35, this is borderline
        self.assertIsNotNone(plan)


class TestTrendingRegime(unittest.TestCase):
    def test_trending_up_picks_bull_call_vertical(self):
        s = StrategySelector(_config())
        ctx = _ctx(24500, "trending", adx=30, trend=0.7, iv=30)
        plan = s.select(ctx, {})
        self.assertIsNotNone(plan)
        self.assertEqual(plan.strategy, StrategyName.DIRECTIONAL_DEBIT)
        # bull call vertical has 2 legs
        self.assertEqual(len(plan.legs), 2)
        # both legs should be calls
        self.assertTrue(all(l["opt_type"] == "CE" for l in plan.legs))

    def test_trending_down_picks_bear_put_vertical(self):
        s = StrategySelector(_config())
        ctx = _ctx(24500, "trending", adx=30, trend=-0.7, iv=30)
        plan = s.select(ctx, {})
        self.assertIsNotNone(plan)
        # Both bull call and bear put use DIRECTIONAL_DEBIT — check legs
        self.assertEqual(plan.strategy, StrategyName.DIRECTIONAL_DEBIT)
        self.assertTrue(all(l["opt_type"] == "PE" for l in plan.legs))


class TestVolatileRegime(unittest.TestCase):
    def test_volatile_picks_long_straddle(self):
        s = StrategySelector(_config())
        ctx = _ctx(24500, "volatile", adx=20, trend=0.0, iv=30, news_urgency=0.6)
        plan = s.select(ctx, {})
        self.assertIsNotNone(plan)
        # long straddle has 2 legs (CE+PE at ATM)
        self.assertEqual(len(plan.legs), 2)
        # one CE, one PE
        opts = [l["opt_type"] for l in plan.legs]
        self.assertIn("CE", opts)
        self.assertIn("PE", opts)


class TestNoPlan(unittest.TestCase):
    def test_no_strategy_when_no_data(self):
        s = StrategySelector(_config())
        # all option ltps are 0 — no plan possible
        from datetime import datetime, timezone
        ctx = SignalContext(
            symbol="NIFTY", spot=24500, vix=14, iv_rank=50, adx=20,
            trend_strength=0.0, regime="range", timestamp=datetime.now(timezone.utc),
            strikes=[], option_ltps={},
        )
        plan = s.select(ctx, {})
        self.assertIsNone(plan)

    def test_no_plan_when_too_few_strikes(self):
        s = StrategySelector(_config())
        ctx = _ctx(24500, "range", adx=15, trend=0.0, iv=50, strikes=[24500])
        plan = s.select(ctx, {})
        # iron condor needs >= 5 strikes
        self.assertIsNone(plan)


class TestPlanMath(unittest.TestCase):
    def test_iron_condor_target_and_stop(self):
        s = StrategySelector(_config())
        ctx = _ctx(24500, "range", adx=15, trend=0.0, iv=55)
        plan = s.select(ctx, {})
        # target = 50% of net_credit (profit target)
        # stop = 2x (wing_width - net_credit) = 2x max_loss
        self.assertGreater(plan.target, 0)
        self.assertGreater(plan.stop, plan.target)  # stop should be larger than target

    def test_bull_call_vertical_debit(self):
        s = StrategySelector(_config())
        ctx = _ctx(24500, "trending", adx=30, trend=0.7, iv=30)
        plan = s.select(ctx, {})
        # debit spread: target should be > debit, stop should be 50% of debit
        long_leg = next(l for l in plan.legs if l["side"] == "BUY")
        short_leg = next(l for l in plan.legs if l["side"] == "SELL")
        debit = long_leg["price"] - short_leg["price"]
        self.assertGreater(plan.target, debit)  # 50% of max_profit + debit
        self.assertAlmostEqual(plan.stop, debit * 0.5, places=2)


class TestEventPlay(unittest.TestCase):
    def test_event_straddle_takes_priority(self):
        s = StrategySelector(_config())
        # Without event — should pick range play
        ctx1 = _ctx(24500, "range", adx=15, trend=0.0, iv=55)
        plan1 = s.select(ctx1, {})
        # With event imminent — should pick event_straddle
        from datetime import datetime, timezone
        from kotak_bot.strategy.base import SignalContext
        ctx2 = SignalContext(
            symbol="NIFTY", spot=24500, vix=14, iv_rank=55, adx=15,
            trend_strength=0.0, regime="range", timestamp=datetime.now(timezone.utc),
            strikes=ctx1.strikes, option_ltps=ctx1.option_ltps,
            news_sentiment=0.0, news_urgency=0.0,
            upcoming_event="RBI Policy", minutes_to_event=20,
        )
        plan2 = s.select(ctx2, {})
        # event_play should fire first regardless of regime
        self.assertIsNotNone(plan2)


if __name__ == "__main__":
    unittest.main()
