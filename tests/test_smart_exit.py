"""Unit tests for smart_exit.evaluate_exit and aggregate_portfolio_greeks.

Covers all 5 exit conditions:
1. Target hit (95% of plan.target)
2. Stop loss (95% of plan.stop)
3. Time decay (within 30 min of expiry, <50% target)
4. Max hold exceeded (1.5x expected, <70% target)
5. Regime flip
6. IV crush (for long-premium strategies)
7. Partial profit-take
"""
import os
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kotak_bot.execution.smart_exit import (
    evaluate_exit,
    aggregate_portfolio_greeks,
    estimate_position_greeks,
    bs_greeks,
)
from kotak_bot.strategy.base import StrategyName


@dataclass
class FakePlan:
    target: float
    stop: float
    expected_hold_minutes: int = 240
    strategy: StrategyName = StrategyName.IRON_CONDOR
    reason: str = "test"
    underlying: str = "NIFTY"
    confidence: float = 0.6
    expiry: str = ""
    legs: list = None


class TestTargetHit(unittest.TestCase):
    def test_target_at_95pct_triggers_exit(self):
        plan = FakePlan(target=100.0, stop=200.0)
        # 95% of target = 95, so 96 should trigger
        es = evaluate_exit(plan, current_pnl=96, pnl_pct=0.96, hold_minutes=10,
                           current_regime="range", current_greeks={},
                           current_iv_change_pct=0.0, minutes_to_expiry=1000)
        self.assertTrue(es.should_exit)
        self.assertIn("target", es.reason.lower())
        self.assertEqual(es.exit_pct, 1.0)

    def test_target_below_95pct_does_not_trigger(self):
        plan = FakePlan(target=100.0, stop=200.0)
        # 80% of target, well below 95%
        es = evaluate_exit(plan, current_pnl=80, pnl_pct=0.80, hold_minutes=10,
                           current_regime="range", current_greeks={},
                           current_iv_change_pct=0.0, minutes_to_expiry=1000)
        self.assertFalse(es.should_exit)


class TestStopHit(unittest.TestCase):
    def test_stop_at_95pct_triggers_exit(self):
        plan = FakePlan(target=100.0, stop=200.0)
        # 95% of stop = 190, so -191 should trigger
        es = evaluate_exit(plan, current_pnl=-191, pnl_pct=-0.95, hold_minutes=10,
                           current_regime="range", current_greeks={},
                           current_iv_change_pct=0.0, minutes_to_expiry=1000)
        self.assertTrue(es.should_exit)
        self.assertIn("stop", es.reason.lower())
        self.assertEqual(es.exit_pct, 1.0)
        self.assertEqual(es.urgency, "urgent")

    def test_stop_just_below_95pct_does_not_trigger(self):
        plan = FakePlan(target=100.0, stop=200.0)
        # 80% of stop, below 95%
        es = evaluate_exit(plan, current_pnl=-160, pnl_pct=-0.80, hold_minutes=10,
                           current_regime="range", current_greeks={},
                           current_iv_change_pct=0.0, minutes_to_expiry=1000)
        self.assertFalse(es.should_exit)


class TestTimeDecay(unittest.TestCase):
    def test_within_30min_and_low_pnl_exits(self):
        plan = FakePlan(target=100.0, stop=200.0)
        # 15 min to expiry, only 30% of target
        es = evaluate_exit(plan, current_pnl=30, pnl_pct=0.30, hold_minutes=10,
                           current_regime="range", current_greeks={},
                           current_iv_change_pct=0.0, minutes_to_expiry=15)
        self.assertTrue(es.should_exit)
        self.assertIn("time decay", es.reason.lower())
        self.assertEqual(es.urgency, "urgent")

    def test_within_30min_but_good_pnl_holds(self):
        plan = FakePlan(target=100.0, stop=200.0)
        # 15 min to expiry but already at 80% of target — let it run
        es = evaluate_exit(plan, current_pnl=80, pnl_pct=0.80, hold_minutes=10,
                           current_regime="range", current_greeks={},
                           current_iv_change_pct=0.0, minutes_to_expiry=15)
        self.assertFalse(es.should_exit)

    def test_more_than_30min_holds(self):
        plan = FakePlan(target=100.0, stop=200.0)
        es = evaluate_exit(plan, current_pnl=30, pnl_pct=0.30, hold_minutes=10,
                           current_regime="range", current_greeks={},
                           current_iv_change_pct=0.0, minutes_to_expiry=60)
        self.assertFalse(es.should_exit)


class TestMaxHoldExceeded(unittest.TestCase):
    def test_over_1_5x_hold_and_low_pnl_exits(self):
        plan = FakePlan(target=100.0, stop=200.0, expected_hold_minutes=100)
        # 1.5x = 150 min, hold 200, pnl 30% (below 70% threshold)
        es = evaluate_exit(plan, current_pnl=30, pnl_pct=0.30, hold_minutes=200,
                           current_regime="range", current_greeks={},
                           current_iv_change_pct=0.0, minutes_to_expiry=1000)
        self.assertTrue(es.should_exit)
        self.assertIn("max hold", es.reason.lower())

    def test_over_hold_but_high_pnl_exits_via_partial(self):
        """Over hold with high pnl (>=50%) triggers partial take, not max-hold.
        Both are valid exits, but partial fires first (lower threshold)."""
        plan = FakePlan(target=100.0, stop=200.0, expected_hold_minutes=100)
        # Over hold + 80% target → partial take (50%) fires before max-hold (70%)
        es = evaluate_exit(plan, current_pnl=80, pnl_pct=0.80, hold_minutes=200,
                           current_regime="range", current_greeks={},
                           current_iv_change_pct=0.0, minutes_to_expiry=1000)
        self.assertTrue(es.should_exit)
        self.assertIn("partial", es.reason.lower())

    def test_short_hold_low_pnl_holds(self):
        """Short hold with low pnl — keep open, no signal."""
        plan = FakePlan(target=100.0, stop=200.0, expected_hold_minutes=240)
        es = evaluate_exit(plan, current_pnl=20, pnl_pct=0.20, hold_minutes=30,
                           current_regime="range", current_greeks={},
                           current_iv_change_pct=0.0, minutes_to_expiry=1000)
        self.assertFalse(es.should_exit)

    def test_under_hold_holds(self):
        plan = FakePlan(target=100.0, stop=200.0, expected_hold_minutes=240)
        # 100 min hold, low pnl — still within bounds
        es = evaluate_exit(plan, current_pnl=20, pnl_pct=0.20, hold_minutes=100,
                           current_regime="range", current_greeks={},
                           current_iv_change_pct=0.0, minutes_to_expiry=1000)
        self.assertFalse(es.should_exit)


class TestRegimeFlip(unittest.TestCase):
    def test_range_strategy_in_trending_market_exits(self):
        plan = FakePlan(target=100.0, stop=200.0, strategy=StrategyName.IRON_CONDOR)
        es = evaluate_exit(plan, current_pnl=20, pnl_pct=0.20, hold_minutes=100,
                           current_regime="trending", current_greeks={},
                           current_iv_change_pct=0.0, minutes_to_expiry=1000)
        self.assertTrue(es.should_exit)
        self.assertIn("regime", es.reason.lower())

    def test_directional_strategy_in_range_market_exits(self):
        plan = FakePlan(target=100.0, stop=200.0, strategy=StrategyName.DIRECTIONAL_DEBIT)
        es = evaluate_exit(plan, current_pnl=20, pnl_pct=0.20, hold_minutes=100,
                           current_regime="range", current_greeks={},
                           current_iv_change_pct=0.0, minutes_to_expiry=1000)
        self.assertTrue(es.should_exit)
        self.assertIn("regime", es.reason.lower())

    def test_regime_match_holds(self):
        plan = FakePlan(target=100.0, stop=200.0, strategy=StrategyName.IRON_CONDOR)
        es = evaluate_exit(plan, current_pnl=20, pnl_pct=0.20, hold_minutes=100,
                           current_regime="range", current_greeks={},
                           current_iv_change_pct=0.0, minutes_to_expiry=1000)
        self.assertFalse(es.should_exit)


class TestIVCrush(unittest.TestCase):
    def test_long_straddle_iv_crush_exits_half(self):
        plan = FakePlan(target=100.0, stop=200.0, strategy=StrategyName.EVENT_STRADDLE)
        # IV dropped 25% (>20% threshold), low pnl
        es = evaluate_exit(plan, current_pnl=20, pnl_pct=0.20, hold_minutes=60,
                           current_regime="volatile", current_greeks={},
                           current_iv_change_pct=-25.0, minutes_to_expiry=1000)
        self.assertTrue(es.should_exit)
        self.assertIn("iv", es.reason.lower())
        # Should be partial exit (50%)
        self.assertEqual(es.exit_pct, 0.5)

    def test_short_strategy_iv_crush_holds(self):
        # IV crush helps short premium, not hurts
        plan = FakePlan(target=100.0, stop=200.0, strategy=StrategyName.IRON_CONDOR)
        es = evaluate_exit(plan, current_pnl=20, pnl_pct=0.20, hold_minutes=60,
                           current_regime="range", current_greeks={},
                           current_iv_change_pct=-25.0, minutes_to_expiry=1000)
        self.assertFalse(es.should_exit)


class TestPartialProfit(unittest.TestCase):
    def test_partial_take_at_50pct(self):
        plan = FakePlan(target=100.0, stop=200.0, expected_hold_minutes=240)
        # 50% target, held 100 min (>30% of expected = 72 min) — partial profit-take
        es = evaluate_exit(plan, current_pnl=50, pnl_pct=0.50, hold_minutes=100,
                           current_regime="range", current_greeks={},
                           current_iv_change_pct=0.0, minutes_to_expiry=1000)
        self.assertTrue(es.should_exit)
        self.assertIn("partial", es.reason.lower())
        self.assertEqual(es.exit_pct, 0.5)

    def test_partial_take_below_50pct_does_not_trigger(self):
        plan = FakePlan(target=100.0, stop=200.0, expected_hold_minutes=240)
        # Only 40% target — not enough for partial take
        es = evaluate_exit(plan, current_pnl=40, pnl_pct=0.40, hold_minutes=100,
                           current_regime="range", current_greeks={},
                           current_iv_change_pct=0.0, minutes_to_expiry=1000)
        self.assertFalse(es.should_exit)


class TestGreeks(unittest.TestCase):
    def test_bs_call_atm_has_positive_delta(self):
        # ATM call, 30 DTE, 18% vol
        g = bs_greeks(100, 100, 30/365, 0.06, 0.18, "CE")
        # ATM delta ~0.5 (slightly > 0.5 due to drift)
        self.assertGreater(g["delta"], 0.45)
        self.assertLess(g["delta"], 0.7)
        # gamma > 0
        self.assertGreater(g["gamma"], 0)
        # vega > 0
        self.assertGreater(g["vega"], 0)
        # theta < 0 (long options lose time)
        self.assertLess(g["theta"], 0)

    def test_bs_put_atm_has_negative_delta(self):
        g = bs_greeks(100, 100, 30/365, 0.06, 0.18, "PE")
        self.assertLess(g["delta"], -0.45)
        self.assertGreater(g["delta"], -0.7)

    def test_call_intrinsic_at_expiry(self):
        # T=0 should give intrinsic value
        g = bs_greeks(110, 100, 0, 0.06, 0.18, "CE")
        self.assertEqual(g["price"], 10.0)
        # delta = 1 if ITM
        self.assertEqual(g["delta"], 1.0)

    def test_call_otm_at_expiry_zero(self):
        g = bs_greeks(90, 100, 0, 0.06, 0.18, "CE")
        self.assertEqual(g["price"], 0.0)
        self.assertEqual(g["delta"], 0.0)


class TestAggregateGreeks(unittest.TestCase):
    def test_aggregate_two_positions(self):
        positions = [
            {"underlying": "NIFTY", "strike": 24500, "option_type": "CE", "qty": 65},
            {"underlying": "NIFTY", "strike": 24500, "option_type": "PE", "qty": 65},
        ]
        # S+P straddle, both ATM, deltas offset (call +0.5, put -0.5)
        g = aggregate_portfolio_greeks(positions, {"NIFTY": 24500}, iv=0.15)
        # Net delta should be near 0 (delta-neutral)
        self.assertLess(abs(g["delta"]), 0.1)
        # But gamma is doubled
        self.assertGreater(g["gamma"], 0)


if __name__ == "__main__":
    unittest.main()
