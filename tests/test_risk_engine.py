"""Unit tests for RiskEngine — covers all 9 risk checks + preset logic.

The 9 checks (in order, in check_new_trade):
1. Market open?
2. Paused?
3. Square-off time?
4. Daily loss cap
5. Weekly loss cap
6. Monthly loss cap
7. Consecutive losses
8. Max trades per day
9. Per-trade max loss
"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kotak_bot.risk.engine import RiskEngine, RiskState, RiskDecision


def _default_config():
    return {
        "initial_capital": 100_000,
        "base": {
            "max_loss_per_trade_pct": 1.0,
            "max_loss_per_trade_abs": 1500,
            "max_daily_loss_pct": 3.0,
            "max_daily_loss_abs": 3000,
            "max_trades_per_day": 6,
            "max_weekly_loss_pct": 6.0,
            "max_monthly_loss_pct": 12.0,
            "max_consecutive_losses": 4,
            "default_lots": 1,
            "max_lots": 3,
        },
        "aggressive": {
            "max_loss_per_trade_pct": 2.0,
            "max_loss_per_trade_abs": 2000,
            "max_daily_loss_pct": 5.0,
            "max_trades_per_day": 10,
            "default_lots": 1,
            "max_lots": 4,
        },
        "defensive": {
            "max_loss_per_trade_pct": 0.5,
            "max_loss_per_trade_abs": 500,
            "max_daily_loss_pct": 1.5,
            "max_trades_per_day": 3,
            "default_lots": 1,
            "max_lots": 1,
        },
        "adapt_to_regime": True,
        "adapt_to_performance": True,
        "high_confidence_threshold": 0.7,
        "low_confidence_threshold": 0.45,
    }


def _patch_market_open(open_=True, square_off=False):
    """Patch the clock helpers so the engine 'thinks' market is open or closed."""
    return patch.multiple(
        "kotak_bot.risk.engine",
        is_market_open=lambda *a, **k: open_,
        is_square_off_time=lambda *a, **k: square_off,
    )


class TestPresetSelection(unittest.TestCase):
    def test_base_default(self):
        cfg = _default_config()
        cfg["adapt_to_regime"] = False
        cfg["adapt_to_performance"] = False
        r = RiskEngine(cfg)
        self.assertEqual(r.pick_preset("range", 0.5, 14.0), "base")

    def test_trending_high_conf_goes_aggressive(self):
        r = RiskEngine(_default_config())
        self.assertEqual(r.pick_preset("trending", 0.8, 14.0), "aggressive")

    def test_volatile_always_defensive(self):
        r = RiskEngine(_default_config())
        self.assertEqual(r.pick_preset("volatile", 0.9, 14.0), "defensive")
        # Even with high confidence, volatile is defensive
        self.assertEqual(r.pick_preset("volatile", 0.5, 14.0), "defensive")

    def test_vix_over_20_forces_defensive(self):
        r = RiskEngine(_default_config())
        # base would normally apply, but high VIX forces defensive
        self.assertEqual(r.pick_preset("range", 0.5, 25.0), "defensive")

    def test_winning_streak_3_bumps_to_aggressive(self):
        r = RiskEngine(_default_config())
        r.state.consecutive_wins = 3
        self.assertEqual(r.pick_preset("range", 0.5, 14.0), "aggressive")


class TestDailyLossCap(unittest.TestCase):
    def test_daily_loss_below_cap_allows(self):
        r = RiskEngine(_default_config())
        r.state.daily_pnl = -1000  # below 3000 cap
        with _patch_market_open(), _patch_market_open(True, False):
            with patch("kotak_bot.risk.engine.is_market_open", return_value=True), \
                 patch("kotak_bot.risk.engine.is_square_off_time", return_value=False):
                dec = r.check_new_trade(plan_max_loss=500, regime="range", confidence=0.5, vix=14.0)
        self.assertTrue(dec.allowed)

    def test_daily_loss_at_cap_blocks(self):
        r = RiskEngine(_default_config())
        r.state.daily_pnl = -3500  # over 3000 cap
        with patch("kotak_bot.risk.engine.is_market_open", return_value=True), \
             patch("kotak_bot.risk.engine.is_square_off_time", return_value=False):
            dec = r.check_new_trade(plan_max_loss=500, regime="range", confidence=0.5, vix=14.0)
        self.assertFalse(dec.allowed)
        self.assertIn("daily", dec.reason.lower())
        self.assertTrue(r.state.paused)


class TestWeeklyMonthlyCap(unittest.TestCase):
    def test_weekly_loss_cap(self):
        r = RiskEngine(_default_config())
        r.state.weekly_pnl = -7000  # over 6% = 6000 cap
        with patch("kotak_bot.risk.engine.is_market_open", return_value=True), \
             patch("kotak_bot.risk.engine.is_square_off_time", return_value=False):
            dec = r.check_new_trade(plan_max_loss=500, regime="range", confidence=0.5, vix=14.0)
        self.assertFalse(dec.allowed)
        self.assertIn("weekly", dec.reason.lower())

    def test_monthly_loss_cap(self):
        r = RiskEngine(_default_config())
        r.state.monthly_pnl = -13000  # over 12% = 12000 cap
        with patch("kotak_bot.risk.engine.is_market_open", return_value=True), \
             patch("kotak_bot.risk.engine.is_square_off_time", return_value=False):
            dec = r.check_new_trade(plan_max_loss=500, regime="range", confidence=0.5, vix=14.0)
        self.assertFalse(dec.allowed)
        self.assertIn("monthly", dec.reason.lower())


class TestConsecutiveLosses(unittest.TestCase):
    def test_consecutive_losses_pauses(self):
        r = RiskEngine(_default_config())
        r.state.consecutive_losses = 5  # > 4 max
        with patch("kotak_bot.risk.engine.is_market_open", return_value=True), \
             patch("kotak_bot.risk.engine.is_square_off_time", return_value=False):
            dec = r.check_new_trade(plan_max_loss=500, regime="range", confidence=0.5, vix=14.0)
        self.assertFalse(dec.allowed)
        self.assertIn("consecutive", dec.reason.lower())
        self.assertTrue(r.state.paused)

    def test_resume_clears_consecutive(self):
        r = RiskEngine(_default_config())
        r.state.consecutive_losses = 5
        r.resume()
        self.assertEqual(r.state.consecutive_losses, 0)
        self.assertFalse(r.state.paused)


class TestMaxTradesPerDay(unittest.TestCase):
    def test_max_trades_blocks(self):
        r = RiskEngine(_default_config())
        r.state.trades_today = 6  # at base cap
        with patch("kotak_bot.risk.engine.is_market_open", return_value=True), \
             patch("kotak_bot.risk.engine.is_square_off_time", return_value=False):
            dec = r.check_new_trade(plan_max_loss=500, regime="range", confidence=0.5, vix=14.0)
        self.assertFalse(dec.allowed)
        self.assertIn("max_trades", dec.reason.lower())


class TestPerTradeCap(unittest.TestCase):
    def test_per_trade_loss_too_big_blocks(self):
        r = RiskEngine(_default_config())
        with patch("kotak_bot.risk.engine.is_market_open", return_value=True), \
             patch("kotak_bot.risk.engine.is_square_off_time", return_value=False):
            dec = r.check_new_trade(plan_max_loss=2000, regime="range", confidence=0.5, vix=14.0)
        self.assertFalse(dec.allowed)
        self.assertIn("per_trade", dec.reason.lower())

    def test_per_trade_loss_within_cap_allows(self):
        r = RiskEngine(_default_config())
        with patch("kotak_bot.risk.engine.is_market_open", return_value=True), \
             patch("kotak_bot.risk.engine.is_square_off_time", return_value=False):
            dec = r.check_new_trade(plan_max_loss=500, regime="range", confidence=0.5, vix=14.0)
        self.assertTrue(dec.allowed)


class TestMarketHours(unittest.TestCase):
    def test_market_closed_blocks(self):
        r = RiskEngine(_default_config())
        with patch("kotak_bot.risk.engine.is_market_open", return_value=False), \
             patch("kotak_bot.risk.engine.is_square_off_time", return_value=False):
            dec = r.check_new_trade(plan_max_loss=500, regime="range", confidence=0.5, vix=14.0)
        self.assertFalse(dec.allowed)
        self.assertIn("market_closed", dec.reason.lower())

    def test_square_off_time_blocks(self):
        r = RiskEngine(_default_config())
        with patch("kotak_bot.risk.engine.is_market_open", return_value=True), \
             patch("kotak_bot.risk.engine.is_square_off_time", return_value=True):
            dec = r.check_new_trade(plan_max_loss=500, regime="range", confidence=0.5, vix=14.0)
        self.assertFalse(dec.allowed)
        self.assertIn("square_off", dec.reason.lower())


class TestPnLTracking(unittest.TestCase):
    def test_on_trade_close_updates_pnl(self):
        r = RiskEngine(_default_config())
        r.on_trade_close(500)
        self.assertEqual(r.state.daily_pnl, 500)
        self.assertEqual(r.state.weekly_pnl, 500)
        self.assertEqual(r.state.monthly_pnl, 500)
        self.assertEqual(r.state.consecutive_wins, 1)
        self.assertEqual(r.state.consecutive_losses, 0)

    def test_on_trade_close_loss_updates_streak(self):
        r = RiskEngine(_default_config())
        r.on_trade_close(-300)
        self.assertEqual(r.state.daily_pnl, -300)
        self.assertEqual(r.state.consecutive_losses, 1)
        self.assertEqual(r.state.consecutive_wins, 0)

    def test_mixed_pnl_resets_streak(self):
        r = RiskEngine(_default_config())
        r.on_trade_close(100)  # win
        r.on_trade_close(-50)  # loss
        self.assertEqual(r.state.consecutive_wins, 0)
        self.assertEqual(r.state.consecutive_losses, 1)


class TestPresetCapsApplied(unittest.TestCase):
    def test_defensive_caps_lower(self):
        """Defensive preset should have lower per-trade cap than base."""
        r = RiskEngine(_default_config())
        # 0.5% of 100k = 500, 0.5% abs = 500, so defensive cap = 500
        r.state.daily_pnl = -200  # not at cap
        r.state.weekly_pnl = -200
        # Force defensive: high VIX
        with patch("kotak_bot.risk.engine.is_market_open", return_value=True), \
             patch("kotak_bot.risk.engine.is_square_off_time", return_value=False):
            dec = r.check_new_trade(plan_max_loss=600, regime="range", confidence=0.5, vix=25.0)
        # 600 > 500 defensive cap → blocked
        self.assertFalse(dec.allowed)
        self.assertEqual(dec.preset, "defensive")

    def test_aggressive_caps_higher(self):
        r = RiskEngine(_default_config())
        with patch("kotak_bot.risk.engine.is_market_open", return_value=True), \
             patch("kotak_bot.risk.engine.is_square_off_time", return_value=False):
            # 1500 loss with trending + high conf → aggressive preset
            # aggressive cap is min(2% of 100k=2000, 2000)=2000, so 1500 < 2000 → allowed
            dec = r.check_new_trade(plan_max_loss=1500, regime="trending", confidence=0.8, vix=12.0)
        self.assertTrue(dec.allowed)
        self.assertEqual(dec.preset, "aggressive")


class TestStaleDataPause(unittest.TestCase):
    def test_on_data_stale_pauses(self):
        r = RiskEngine(_default_config())
        r.on_data_stale("NIFTY")
        self.assertTrue(r.state.paused)
        self.assertIn("data_stale", r.state.pause_reason)


if __name__ == "__main__":
    unittest.main()
