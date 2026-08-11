"""Tests for configurability — verifies nothing critical is hardcoded.

These tests catch regressions where someone adds a magic number to runtime code
instead of pulling it from settings.yaml. The 'no hardcodes' rule is enforced
by these tests for the most important values.
"""
import os
import sys
import unittest
from datetime import datetime, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kotak_bot.utils.clock import (
    set_market_hours, get_market_hours, is_market_open, is_square_off_time,
    _MARKET_HOURS,
)
from kotak_bot.execution.smart_exit import evaluate_exit, DEFAULT_CONFIG
from kotak_bot.strategy.base import StrategyName, TradePlan
from kotak_bot.broker.paper_client import PaperClient


class TestMarketHoursConfigurable(unittest.TestCase):
    def setUp(self):
        # Reset to defaults
        set_market_hours({})
        _MARKET_HOURS.update({
            "pre_open_start": time(9, 0),
            "pre_open_end": time(9, 15),
            "opening_end": time(9, 30),
            "regular_end": time(15, 0),
            "close": time(15, 30),
            "square_off": time(15, 15),
        })

    def test_default_hours_match_nse(self):
        h = get_market_hours()
        self.assertEqual(h["pre_open_start"], time(9, 0))
        self.assertEqual(h["close"], time(15, 30))

    def test_set_market_hours_overrides(self):
        set_market_hours({
            "pre_open_start": "08:00",
            "pre_open_end": "08:15",
            "square_off": "14:00",
            "close": "14:30",
        })
        h = get_market_hours()
        self.assertEqual(h["pre_open_start"], time(8, 0))
        self.assertEqual(h["square_off"], time(14, 0))
        self.assertEqual(h["close"], time(14, 30))
        # others keep default
        self.assertEqual(h["opening_end"], time(9, 30))

    def test_set_market_hours_invalid_string_ignored(self):
        set_market_hours({"pre_open_start": "not-a-time", "close": "25:99"})
        h = get_market_hours()
        # both should be unchanged (default)
        self.assertEqual(h["pre_open_start"], time(9, 0))
        self.assertEqual(h["close"], time(15, 30))

    def test_set_market_hours_partial_override(self):
        set_market_hours({"square_off": "14:45"})
        h = get_market_hours()
        self.assertEqual(h["square_off"], time(14, 45))
        # close unchanged
        self.assertEqual(h["close"], time(15, 30))


class TestSmartExitConfigurable(unittest.TestCase):
    def _plan(self):
        return TradePlan(
            strategy=StrategyName.IRON_CONDOR,
            underlying="NIFTY",
            legs=[],
            target=100.0, stop=200.0, confidence=0.5, reason="",
            expected_hold_minutes=240,
        )

    def test_default_thresholds_applied(self):
        plan = self._plan()
        # at exactly target_pct default (0.95) of target = 95, should exit
        es = evaluate_exit(plan, current_pnl=95, pnl_pct=0.95, hold_minutes=10,
                           current_regime="range", current_greeks={},
                           current_iv_change_pct=0.0, minutes_to_expiry=1000)
        self.assertTrue(es.should_exit)

    def test_overridden_target_threshold(self):
        plan = self._plan()
        # Lower the target threshold to 0.5: at 60% of target should now exit
        cfg = {"target_pct": 0.5}
        es = evaluate_exit(plan, current_pnl=60, pnl_pct=0.60, hold_minutes=10,
                           current_regime="range", current_greeks={},
                           current_iv_change_pct=0.0, minutes_to_expiry=1000,
                           config=cfg)
        self.assertTrue(es.should_exit, "with target_pct=0.5, hitting 60% target should trigger exit")

    def test_overridden_expiry_threshold(self):
        plan = self._plan()
        # Default 30 min. Override to 15 min: now 25 min is NOT close to expiry.
        # (Default 30 would have fired at 25 min.)
        cfg = {"expiry_minutes_threshold": 15}
        es = evaluate_exit(plan, current_pnl=30, pnl_pct=0.30, hold_minutes=10,
                           current_regime="range", current_greeks={},
                           current_iv_change_pct=0.0, minutes_to_expiry=25,
                           config=cfg)
        self.assertFalse(es.should_exit, "with 15-min threshold, 25 min is not 'close to expiry'")
        # And at 10 min it should fire (below 15)
        es2 = evaluate_exit(plan, current_pnl=30, pnl_pct=0.30, hold_minutes=10,
                            current_regime="range", current_greeks={},
                            current_iv_change_pct=0.0, minutes_to_expiry=10,
                            config=cfg)
        self.assertTrue(es2.should_exit)

    def test_overridden_max_hold_multiplier(self):
        plan = self._plan()
        # Default 1.5x. Override to 2.0x: at 200 min hold (just under 2x) and low pnl, no exit
        cfg = {"max_hold_multiplier": 2.0}
        es = evaluate_exit(plan, current_pnl=30, pnl_pct=0.30, hold_minutes=200,
                           current_regime="range", current_greeks={},
                           current_iv_change_pct=0.0, minutes_to_expiry=1000,
                           config=cfg)
        self.assertFalse(es.should_exit, "with 2.0x multiplier, 200 min is not over")

    def test_overridden_iv_crush_threshold(self):
        plan = self._plan()
        plan.strategy = StrategyName.EVENT_STRADDLE
        # Default -20%. Override to -10%: a 12% drop should now trigger
        cfg = {"iv_crush_pct": -10.0}
        es = evaluate_exit(plan, current_pnl=10, pnl_pct=0.10, hold_minutes=60,
                           current_regime="volatile", current_greeks={},
                           current_iv_change_pct=-12.0, minutes_to_expiry=1000,
                           config=cfg)
        self.assertTrue(es.should_exit, "with iv_crush_pct=-10%, a 12% drop should trigger")


class TestPaperClientConfigurable(unittest.TestCase):
    def test_default_slippage_bps(self):
        c = PaperClient.__init__.__defaults__[1]  # slippage_bps
        self.assertEqual(c, 5.0)

    def test_custom_slippage_bps(self):
        c = PaperClient(starting_capital=100_000, slippage_bps=10.0)
        self.assertEqual(c.slippage_bps, 10.0)

    def test_default_spread_config(self):
        c = PaperClient(starting_capital=100_000)
        self.assertEqual(c.limit_fill_spread_pct, 0.1)
        self.assertEqual(c.limit_fill_min_spread, 0.05)

    def test_custom_spread_config(self):
        c = PaperClient(
            starting_capital=100_000,
            limit_fill_spread_pct=0.2,
            limit_fill_min_spread=0.10,
        )
        self.assertEqual(c.limit_fill_spread_pct, 0.2)
        self.assertEqual(c.limit_fill_min_spread, 0.10)

    def test_spread_actually_used_in_fill(self):
        """Verify the configurable spread actually affects fill math (uses temp path)."""
        import tempfile
        tmp = tempfile.NamedTemporaryFile(suffix='.json', delete=False, mode='w')
        tmp.close()
        try:
            c = PaperClient(
                starting_capital=100_000,
                limit_fill_spread_pct=1.0,  # 1% spread (large)
                limit_fill_min_spread=0.01,
                persist_path=tmp.name,  # isolate from production state
            )
            c.connect()
            from kotak_bot.broker.base import Tick, Order, OrderSide, OrderType, ProductType
            c.inject_tick(Tick(symbol="X", ltp=100.0, exchange="NFO"))
            # BUY LIMIT at 100.5: with 1% spread, ask=101, 100.5 < 101 → no fill
            order = Order(
                symbol="X", side=OrderSide.BUY, qty=10, order_type=OrderType.LIMIT,
                product=ProductType.MIS, price=100.5, exchange="NFO",
            )
            placed = c.place_order(order)
            # Use the return value (not _orders.values()[0] which would be a
            # disk-loaded order from a previous test)
            o = placed
            self.assertEqual(o.status.value, "open", f"with 1% spread, 100.5 should not fill, got {o.avg_fill_price}")
        finally:
            if os.path.exists(tmp.name):
                os.unlink(tmp.name)


class TestSettingsYamlHasAllConfig(unittest.TestCase):
    """Verify settings.yaml has the keys that the code reads."""

    def setUp(self):
        self.path = ROOT / "config" / "settings.yaml"
        self.text = self.path.read_text(encoding="utf-8")
        try:
            import yaml
            self.cfg = yaml.safe_load(self.text)
        except ImportError:
            self.cfg = None

    def test_yaml_loads(self):
        if self.cfg is None:
            self.skipTest("yaml not installed")
        self.assertIsInstance(self.cfg, dict)

    def test_broker_keys(self):
        if self.cfg is None: self.skipTest("yaml not installed")
        b = self.cfg.get("broker", {})
        self.assertIn("paper_capital", b)
        self.assertIn("limit_fill_spread_pct", b)
        self.assertIn("limit_fill_min_spread", b)

    def test_market_hours_keys(self):
        if self.cfg is None: self.skipTest("yaml not installed")
        m = self.cfg.get("market_hours", {})
        for k in ("pre_open_start", "pre_open_end", "opening_end", "regular_end",
                  "close", "square_off"):
            self.assertIn(k, m, f"market_hours.{k} missing from settings.yaml")
            self.assertRegex(m[k], r"^\d{2}:\d{2}$", f"market_hours.{k} should be HH:MM")

    def test_smart_exit_keys(self):
        if self.cfg is None: self.skipTest("yaml not installed")
        se = self.cfg.get("risk", {}).get("smart_exit", {})
        for k in ("target_pct", "stop_pct", "min_hold_pnl_pct",
                  "expiry_minutes_threshold", "max_hold_multiplier",
                  "max_hold_pnl_pct", "iv_crush_pct", "iv_crush_pnl_pct",
                  "partial_profit_low", "partial_profit_high",
                  "partial_profit_hold_pct", "regime_flip_pnl_pct"):
            self.assertIn(k, se, f"risk.smart_exit.{k} missing from settings.yaml")

    def test_instruments_keys(self):
        if self.cfg is None: self.skipTest("yaml not installed")
        i = self.cfg.get("instruments", {})
        self.assertIn("lot_sizes", i)
        self.assertIn("strike_step", i)
        # strike_padding is at risk.strike_padding in current config
        self.assertIn("NIFTY", i["strike_step"])
        self.assertIn("BANKNIFTY", i["strike_step"])
        # risk.strike_padding is also there
        self.assertIn("strike_padding", self.cfg.get("risk", {}))

    def test_risk_keys(self):
        if self.cfg is None: self.skipTest("yaml not installed")
        r = self.cfg.get("risk", {})
        for k in ("base", "aggressive", "defensive"):
            self.assertIn(k, r, f"risk.{k} missing")
            for sk in ("max_loss_per_trade_pct", "max_loss_per_trade_abs",
                       "max_daily_loss_pct", "max_trades_per_day",
                       "default_lots", "max_lots"):
                self.assertIn(sk, r[k], f"risk.{k}.{sk} missing")


if __name__ == "__main__":
    unittest.main()
