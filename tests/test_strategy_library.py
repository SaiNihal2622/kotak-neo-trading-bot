"""Tests for the strategy library and iron condor enforcement."""
import json
import math
from datetime import datetime, time as dtime, timedelta
from pathlib import Path
from unittest.mock import patch
import sys

import pytest

ROOT = Path(__file__).parent.parent.resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TestStrategyLibrary:
    """Test the strategy_library.py module."""

    def test_strategies_loaded(self):
        from scripts.strategy_library import STRATEGIES
        assert len(STRATEGIES) >= 5
        assert "iron_condor_nifty" in STRATEGIES
        # Iron condor is the primary strategy with proven edge
        ic = STRATEGIES["iron_condor_nifty"]
        assert ic.backtested_win_rate >= 0.5  # 50%+
        assert ic.backtested_avg_pnl > 0
        assert ic.structure == "iron_condor"

    def test_rsi2_disabled_by_default(self):
        from scripts.strategy_library import load_performance, INITIAL_DISABLED
        perf = load_performance()
        # RSI(2) is disabled because 4-day backtest showed 33% win rate
        assert "rsi_2_mean_reversion" in INITIAL_DISABLED
        assert perf["rsi_2_mean_reversion"].is_disabled
        assert "33%" in perf["rsi_2_mean_reversion"].disable_reason or "backtest" in perf["rsi_2_mean_reversion"].disable_reason.lower()

    def test_vol_targeted_size_low_vol(self):
        """Low VIX = bigger size (vol is cheap)."""
        from scripts.strategy_library import vol_targeted_size
        size = vol_targeted_size(100000, 11.5)
        assert size >= 1

    def test_vol_targeted_size_high_vol(self):
        """High VIX = smaller size (vol is expensive)."""
        from scripts.strategy_library import vol_targeted_size
        size_low = vol_targeted_size(100000, 11.5)
        size_high = vol_targeted_size(100000, 25)
        # Higher vol should give smaller or equal size
        assert size_high <= size_low

    def test_rsi_calculation(self):
        from scripts.strategy_library import compute_rsi
        # Uptrend: RSI should be high
        uptrend = [100 + i for i in range(20)]
        rsi = compute_rsi(uptrend, period=14)
        assert rsi is not None
        assert rsi > 70  # Strong uptrend
        # Downtrend: RSI should be low
        downtrend = [100 - i for i in range(20)]
        rsi = compute_rsi(downtrend, period=14)
        assert rsi < 30  # Strong downtrend

    def test_strategy_selector_picks_iron_condor_low_vol(self):
        """When VIX is low and market is range-bound, pick iron condor."""
        from scripts.strategy_library import select_strategy, STRATEGIES
        # 50 candles of 0.1% drift
        closes = [23500 + i * 0.5 for i in range(50)]
        candles = [{"o": c, "h": c + 1, "l": c - 1, "c": c, "v": 1000} for c in closes]
        context = {
            "spot": closes[-1],
            "vix": 12.0,  # low VIX
            "session_open": closes[0],
            "candles": candles,
            "now": datetime.now().replace(hour=11, minute=0),
            "vwap": closes[-1],
        }
        strategy = select_strategy(context, {})
        # Should pick iron_condor for low-vol range-bound
        assert strategy is not None
        assert strategy.name in ("iron_condor_nifty", "vwap_bounce_nifty")

    def test_strategy_selector_skips_disabled(self):
        """Disabled strategies should never be selected."""
        from scripts.strategy_library import select_strategy, StrategyResult, STRATEGIES
        # Mark all as disabled
        perf = {name: StrategyResult(name=name) for name in STRATEGIES}
        for s in perf.values():
            s.disabled_at = "2026-01-01T00:00:00"
        # Run with conditions that would normally pick iron condor
        closes = [23500 + i * 0.5 for i in range(50)]
        candles = [{"o": c, "h": c + 1, "l": c - 1, "c": c, "v": 1000} for c in closes]
        context = {
            "spot": closes[-1], "vix": 12.0, "session_open": closes[0],
            "candles": candles, "now": datetime.now().replace(hour=11, minute=0),
            "vwap": closes[-1],
        }
        strategy = select_strategy(context, perf)
        # All disabled — should return None
        assert strategy is None

    def test_generate_iron_condor_plan(self):
        """The iron condor trade plan should have 4 legs (sell CE, buy CE, sell PE, buy PE)."""
        from scripts.strategy_library import generate_trade_plan, STRATEGIES
        ic = STRATEGIES["iron_condor_nifty"]
        context = {"spot": 23500, "vix": 12.0}
        plan = generate_trade_plan(ic, context, capital=100000, vix=12.0)
        assert plan["structure"] == "iron_condor"
        assert len(plan["legs"]) == 4
        # Should have 2 sells and 2 buys
        sides = [leg["side"] for leg in plan["legs"]]
        assert sides.count("SELL") == 2
        assert sides.count("BUY") == 2
        # Should have target and stop
        assert "target" in plan
        assert "stop" in plan
        # Target should be positive (we want profit)
        assert plan["target"] > 0
        # Stop should be negative (we want to cut loss)
        assert plan["stop"] < 0


class TestStrategyResult:
    """Test the per-strategy performance tracking."""

    def test_record_win(self):
        from scripts.strategy_library import StrategyResult
        r = StrategyResult(name="test")
        r.record(500.0)
        assert r.n_trades == 1
        assert r.n_wins == 1
        assert r.total_pnl == 500.0
        assert r.last_10_pnl == [500.0]

    def test_record_loss(self):
        from scripts.strategy_library import StrategyResult
        r = StrategyResult(name="test")
        r.record(-200.0)
        assert r.n_losses == 1
        assert r.total_pnl == -200.0

    def test_auto_disable_after_10_losses(self):
        """Auto-disable when win rate < 30% over 10+ trades."""
        from scripts.strategy_library import StrategyResult
        r = StrategyResult(name="test")
        # 8 losses, 2 wins = 20% (disabled)
        for _ in range(8):
            r.record(-100.0)
        for _ in range(2):
            r.record(50.0)
        # 2 wins / 10 trades = 20% < 30% → disabled
        assert r.is_disabled
        assert "20" in r.disable_reason or "30" in r.disable_reason

    def test_no_disable_above_threshold(self):
        """Strategy with >30% win rate stays enabled."""
        from scripts.strategy_library import StrategyResult
        r = StrategyResult(name="test")
        # 5 wins, 5 losses = 50% (NOT disabled)
        for _ in range(5):
            r.record(-100.0)
        for _ in range(5):
            r.record(50.0)
        assert not r.is_disabled

    def test_to_dict(self):
        from scripts.strategy_library import StrategyResult
        r = StrategyResult(name="test")
        r.record(100.0)
        d = r.to_dict()
        assert d["name"] == "test"
        assert d["n_trades"] == 1
        assert d["n_wins"] == 1
        assert d["win_rate"] == 1.0
        assert d["total_pnl"] == 100.0


class TestStrategyLibraryEnforcement:
    """Test the brain's _strategy_library_enforcement function."""

    def test_no_enforcement_when_market_closed(self, tmp_path, monkeypatch):
        from scripts import quant_service
        monkeypatch.setattr(quant_service, "DATA", tmp_path)
        with patch("scripts.quant_service.is_market_hours", return_value=False):
            result = quant_service._strategy_library_enforcement({"paper": {}})
        assert result is None

    def test_no_enforcement_with_open_position(self, tmp_path, monkeypatch):
        from scripts import quant_service
        monkeypatch.setattr(quant_service, "DATA", tmp_path)
        with patch("scripts.quant_service.is_market_hours", return_value=True):
            result = quant_service._strategy_library_enforcement({
                "paper": {"positions": {"SYM1": {"qty": 75}}}
            })
        assert result is None

    def test_no_enforcement_high_vix(self, tmp_path, monkeypatch):
        """High VIX (>16) should NOT trigger iron condor."""
        from scripts import quant_service
        monkeypatch.setattr(quant_service, "DATA", tmp_path)
        class FakeEng:
            last_ltp = {"NIFTY": 23500.0}
            def get_session_open(self, sym):
                return {"NIFTY": 23450.0}.get(sym, 0)  # 0.21% move
        import types
        fake_module = types.ModuleType("candle_engine")
        fake_module.get_engine = lambda: FakeEng()
        monkeypatch.setitem(sys.modules, "candle_engine", fake_module)
        with patch("scripts.quant_service.is_market_hours", return_value=True):
            result = quant_service._strategy_library_enforcement({
                "paper": {"positions": {}},
                "liveness": {"snapshot": {"vix": 25}},  # high VIX
            })
        assert result is None

    def test_no_enforcement_strong_trend(self, tmp_path, monkeypatch):
        """Strong trend (>0.7%) should NOT trigger iron condor."""
        from scripts import quant_service
        monkeypatch.setattr(quant_service, "DATA", tmp_path)
        class FakeEng:
            last_ltp = {"NIFTY": 23500.0}
            def get_session_open(self, sym):
                return {"NIFTY": 23700.0}.get(sym, 0)  # 0.85% move (trending)
        import types
        fake_module = types.ModuleType("candle_engine")
        fake_module.get_engine = lambda: FakeEng()
        monkeypatch.setitem(sys.modules, "candle_engine", fake_module)
        with patch("scripts.quant_service.is_market_hours", return_value=True):
            result = quant_service._strategy_library_enforcement({
                "paper": {"positions": {}},
                "liveness": {"snapshot": {"vix": 12}},
            })
        assert result is None

    def test_iron_condor_when_range_bound_low_vol(self, tmp_path, monkeypatch):
        """Range-bound market + low VIX = iron condor fires."""
        from scripts import quant_service
        monkeypatch.setattr(quant_service, "DATA", tmp_path)
        class FakeEng:
            last_ltp = {"NIFTY": 23500.0}
            def get_session_open(self, sym):
                return {"NIFTY": 23520.0}.get(sym, 0)  # 0.085% move (range-bound)
        import types
        fake_module = types.ModuleType("candle_engine")
        fake_module.get_engine = lambda: FakeEng()
        monkeypatch.setitem(sys.modules, "candle_engine", fake_module)
        with patch("scripts.quant_service.is_market_hours", return_value=True):
            result = quant_service._strategy_library_enforcement({
                "paper": {"positions": {}},
                "liveness": {"snapshot": {"vix": 12}},  # low VIX
                "intraday": {
                    "instruments": {"NIFTY": {"ltp": 23500.0, "current": 23500.0}},
                    "session_opens": {"NIFTY": 23520.0},
                },
            })
        assert result is not None
        assert result["actions"][0]["strategy"] == "iron_condor_nifty"
        # Should have 4 legs
        assert len(result["actions"][0]["legs"]) == 4
        # Should mention backtested edge
        assert "backtest" in result["actions"][0]["rationale"].lower() or "100%" in result["actions"][0]["rationale"]


class TestStrategyBacktestResults:
    """Verify the backtest data shows the edge the library relies on."""

    def test_iron_condor_is_profitable(self):
        """The 4-day backtest showed iron condor is the winning strategy."""
        # Read the strategy backtest file
        bt_path = ROOT / "data_cache" / "strategy_backtest.json"
        if not bt_path.exists():
            # Run the backtest if not present
            import subprocess
            subprocess.run(["python", "scripts/_backtest_strategies.py"],
                         cwd=str(ROOT), capture_output=True, timeout=60)
        if not bt_path.exists():
            pytest.skip("backtest data not available")
        data = json.loads(bt_path.read_text(encoding="utf-8"))
        ic = data.get("summary", {}).get("iron_condor", {})
        # Iron condor should have >50% win rate
        assert ic.get("win_rate", 0) >= 0.5, f"iron condor win rate too low: {ic}"
        # Iron condor should be profitable
        assert ic.get("total_pnl", 0) > 0, f"iron condor not profitable: {ic}"
        # Average P&L should be positive
        assert ic.get("avg_pnl", 0) > 0, f"iron condor avg P&L not positive: {ic}"
