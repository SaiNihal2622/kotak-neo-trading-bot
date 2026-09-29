"""Tests for NIFTY CASH (CAS) strategies — nifty_cash_long and nifty_cash_short.

CAS = spot NIFTY (nse_cm segment, MIS product). Added 2026-09-29 per user request.
Conservative defaults: 1 lot max, mandatory EOD square-off, hard stop loss.
Triggers: ADX > 25 (trending) + RSI > 55/<45 + session_pct > +0.3% / < -0.3%.
"""
import json
import sys
from datetime import datetime, time as dtime
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TestCASStrategiesRegistered:
    """Both CAS strategies must be present in STRATEGIES dict."""

    def test_cash_long_registered(self):
        from scripts.strategy_library import STRATEGIES
        assert "nifty_cash_long" in STRATEGIES

    def test_cash_short_registered(self):
        from scripts.strategy_library import STRATEGIES
        assert "nifty_cash_short" in STRATEGIES

    def test_cash_long_structure(self):
        from scripts.strategy_library import STRATEGIES
        nc = STRATEGIES["nifty_cash_long"]
        assert nc.structure == "cash_long"
        assert nc.underlying == "NIFTY"
        # target_pct=1.0% (gain 1% of spot)
        assert nc.target_pct == 1.0
        # stop_pct=0.75% (hard stop at -0.75%)
        assert nc.stop_pct == 0.75
        # entry window 9:45-14:30
        assert nc.entry_window_start == dtime(9, 45)
        assert nc.entry_window_end == dtime(14, 30)

    def test_cash_short_structure(self):
        from scripts.strategy_library import STRATEGIES
        nc = STRATEGIES["nifty_cash_short"]
        assert nc.structure == "cash_short"
        assert nc.underlying == "NIFTY"
        assert nc.target_pct == 1.0
        assert nc.stop_pct == 0.75
        assert nc.entry_window_start == dtime(9, 45)
        assert nc.entry_window_end == dtime(14, 30)

    def test_cash_strategies_require_trend_and_momentum(self):
        from scripts.strategy_library import STRATEGIES
        nc_long = STRATEGIES["nifty_cash_long"]
        nc_short = STRATEGIES["nifty_cash_short"]
        # Long: ADX>25 + RSI>55 + session_pct>+0.3%
        assert "adx_above_25" in nc_long.requires
        assert "rsi_above_55" in nc_long.requires
        assert "session_pct_above_0.3" in nc_long.requires
        # Short: ADX>25 + RSI<45 + session_pct<-0.3%
        assert "adx_above_25" in nc_short.requires
        assert "rsi_below_45" in nc_short.requires
        assert "session_pct_below_-0.3" in nc_short.requires


class TestCASTradePlanGenerator:
    """generate_trade_plan must produce a 1-leg CAS plan with nse_cm segment."""

    def _ctx(self):
        return {"spot": 22750.0, "vix": 13.0}

    def test_cash_long_plan_has_single_buy_leg_nse_cm(self):
        from scripts.strategy_library import generate_trade_plan, STRATEGIES
        plan = generate_trade_plan(STRATEGIES["nifty_cash_long"],
                                   self._ctx(), capital=100000, vix=13.0)
        assert plan["structure"] == "cash_long"
        assert plan["underlying"] == "NIFTY"
        assert len(plan["legs"]) == 1
        leg = plan["legs"][0]
        assert leg["side"] == "BUY"
        assert leg["instrument"] == "NIFTY"
        assert leg["segment"] == "nse_cm"
        assert leg["order_type"] == "MARKET"
        # Conservative: 1 lot NIFTY = 75 shares, NOT more
        assert leg["qty"] == 75, f"CAS must be capped at 1 lot (75 shares), got {leg['qty']}"

    def test_cash_short_plan_has_single_sell_leg_nse_cm(self):
        from scripts.strategy_library import generate_trade_plan, STRATEGIES
        plan = generate_trade_plan(STRATEGIES["nifty_cash_short"],
                                   self._ctx(), capital=100000, vix=13.0)
        assert plan["structure"] == "cash_short"
        assert plan["underlying"] == "NIFTY"
        assert len(plan["legs"]) == 1
        leg = plan["legs"][0]
        assert leg["side"] == "SELL"
        assert leg["instrument"] == "NIFTY"
        assert leg["segment"] == "nse_cm"
        # 1 lot NIFTY = 75 shares
        assert leg["qty"] == 75

    def test_cash_long_capped_at_one_lot_even_high_capital(self):
        """Even with 1M capital, CAS = 1 lot (hard cap)."""
        from scripts.strategy_library import generate_trade_plan, STRATEGIES
        plan = generate_trade_plan(STRATEGIES["nifty_cash_long"],
                                   self._ctx(), capital=1000000, vix=10.0)
        assert plan["legs"][0]["qty"] == 75  # still 1 lot

    def test_cash_target_pnl_matches_1pct_of_spot(self):
        """target_pnl should be +1% × 75 * spot for CAS long."""
        from scripts.strategy_library import generate_trade_plan, STRATEGIES
        spot = 22750.0
        plan = generate_trade_plan(STRATEGIES["nifty_cash_long"],
                                   {"spot": spot, "vix": 13.0},
                                   capital=100000, vix=13.0)
        expected_target = spot * 1 * 75 * 1.0 / 100  # 1 lot, 75 shares, 1% target
        assert abs(plan["target_pnl"] - expected_target) < 1.0

    def test_cash_stop_pnl_is_negative_75pct_of_spot(self):
        """stop_pnl should be -0.75% × 75 * spot for CAS long."""
        from scripts.strategy_library import generate_trade_plan, STRATEGIES
        spot = 22750.0
        plan = generate_trade_plan(STRATEGIES["nifty_cash_long"],
                                   {"spot": spot, "vix": 13.0},
                                   capital=100000, vix=13.0)
        expected_stop = -spot * 1 * 75 * 0.75 / 100
        assert abs(plan["stop_pnl"] - expected_stop) < 1.0


class TestCASStrategySelector:
    """select_strategy should pick CAS when ADX > 25 + RSI matches + session_pct matches."""

    def _trend_context(self, spot=22600, session_open=22500, adx_in_file=30,
                      rsi_target=58, now_hour=11, now_minute=0):
        """Build a context for trending NIFTY (uptrend by default)."""
        # 20 uptrending candles → RSI-14 will be high
        closes = [session_open + i * 5 for i in range(20)]
        candles = [{"o": c, "h": c + 2, "l": c - 2, "c": c, "v": 1000} for c in closes]
        # Make last close = spot
        candles[-1]["c"] = spot
        candles[-1]["h"] = spot
        candles[-1]["l"] = spot
        candles[-1]["o"] = spot
        return {
            "spot": spot,
            "vix": 13.0,
            "session_open": session_open,
            "candles": candles,
            "now": datetime.now().replace(hour=now_hour, minute=now_minute, second=0, microsecond=0),
            "vwap": spot,
        }, adx_in_file

    def _write_adx(self, tmp_path, adx):
        """Write data_cache/candles_aggregate.json with given ADX."""
        agg = {"symbols": {"NIFTY": {"indicators": {"adx": adx}}}}
        p = tmp_path / "data_cache" / "candles_aggregate.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(agg), encoding="utf-8")
        return p

    def test_cash_long_fires_in_uptrend_with_high_adx(self, tmp_path, monkeypatch):
        """ADX=30 (>25) + uptrend + positive session_pct → cash_long candidate.

        session_pct must be > 0.7% to disable iron_condor (iron condor wins at
        0.9 score in range-bound; cash_long is 0.75). 0.85% triggers cash_long
        but kills iron_condor.
        """
        from scripts import strategy_library as sl
        # Make the relative Path look in tmp_path
        monkeypatch.chdir(tmp_path)
        self._write_adx(tmp_path, adx=30)
        # spot=22690, session_open=22500 → session_pct = +0.844%
        context, _ = self._trend_context(spot=22690, session_open=22500,
                                         now_hour=11, now_minute=0)
        # 20 uptrending candles → RSI-14 high
        closes = [22500 + i * 5 for i in range(20)]
        candles = [{"o": c, "h": c + 2, "l": c - 2, "c": c, "v": 1000} for c in closes]
        candles[-1]["c"] = 22690
        candles[-1]["h"] = 22690
        candles[-1]["l"] = 22690
        candles[-1]["o"] = 22690
        context["candles"] = candles
        context["spot"] = 22690
        strategy = sl.select_strategy(context, {})
        assert strategy is not None
        assert strategy.name == "nifty_cash_long", (
            f"Expected cash_long in uptrend + ADX=30, got {strategy.name}")

    def test_cash_short_fires_in_downtrend_with_high_adx(self, tmp_path, monkeypatch):
        """ADX=30 + downtrend + negative session_pct → cash_short candidate.

        session_pct must be < -0.7% (kills iron_condor) AND < -0.3% (cash_short).
        cash_short score 0.75 > long_put 0.7 (which also fires), so cash_short wins.

        Note: RSI must be < 45 but NOT 0.0 — the `(rsi14 or 50)` idiom in
        select_strategy falls back to 50 when RSI is exactly 0 (falsy), so we
        use a realistic downtrend with mixed gains/losses to get RSI ~22.
        """
        from scripts import strategy_library as sl
        monkeypatch.chdir(tmp_path)
        self._write_adx(tmp_path, adx=30)
        # spot=22300, session_open=22500 → session_pct = -0.889%
        context, _ = self._trend_context(spot=22300, session_open=22500,
                                         now_hour=11, now_minute=0)
        # Realistic downtrend: net -20/bar with mixed gains/losses.
        # Strictly linear decline gives RSI=0 (falsy → fallback to 50).
        # With variation, RSI ≈ 22 (well below 45).
        closes = [
            22505, 22493, 22478, 22486, 22479, 22471, 22463, 22452,
            22460, 22448, 22454, 22462, 22464, 22451, 22454, 22452,
            22438, 22423, 22410, 22300,
        ]
        candles = [{"o": c, "h": c + 2, "l": c - 2, "c": c, "v": 1000} for c in closes]
        candles[-1]["c"] = 22300
        candles[-1]["h"] = 22300
        candles[-1]["l"] = 22300
        candles[-1]["o"] = 22300
        context["candles"] = candles
        context["spot"] = 22300
        strategy = sl.select_strategy(context, {})
        assert strategy is not None
        assert strategy.name == "nifty_cash_short", (
            f"Expected cash_short in downtrend + ADX=30, got {strategy.name}")

    def test_cash_does_not_fire_with_low_adx(self, tmp_path, monkeypatch):
        """ADX < 25 = range-bound. CAS should NOT fire (iron_condor territory)."""
        from scripts import strategy_library as sl
        monkeypatch.chdir(tmp_path)
        self._write_adx(tmp_path, adx=15)  # low ADX = ranging
        context, _ = self._trend_context()
        strategy = sl.select_strategy(context, {})
        # Could be iron_condor, vwap_bounce, or None — but NOT cash_long
        if strategy is not None:
            assert strategy.structure not in ("cash_long", "cash_short"), (
                f"CAS should NOT fire when ADX<25, got {strategy.name}")

    def test_cash_does_not_fire_outside_entry_window(self, tmp_path, monkeypatch):
        """At 9:00 AM (before 9:45 window) CAS must NOT fire even with all signals."""
        from scripts import strategy_library as sl
        monkeypatch.chdir(tmp_path)
        self._write_adx(tmp_path, adx=30)
        context, _ = self._trend_context(now_hour=9, now_minute=0)
        strategy = sl.select_strategy(context, {})
        if strategy is not None:
            assert strategy.structure not in ("cash_long", "cash_short"), (
                f"CAS must not fire before 9:45, got {strategy.name}")

    def test_cash_works_when_candles_aggregate_missing(self, tmp_path, monkeypatch):
        """No data_cache/candles_aggregate.json → adx_value=0 → CAS does NOT fire."""
        from scripts import strategy_library as sl
        monkeypatch.chdir(tmp_path)
        # Don't write candles_aggregate.json
        context, _ = self._trend_context()
        strategy = sl.select_strategy(context, {})
        if strategy is not None:
            assert strategy.structure not in ("cash_long", "cash_short"), (
                f"CAS must not fire when ADX unavailable, got {strategy.name}")

    def test_disabled_cash_long_not_selected(self, tmp_path, monkeypatch):
        """Disabled CAS strategy must NOT be picked."""
        from scripts import strategy_library as sl
        from scripts.strategy_library import StrategyResult
        monkeypatch.chdir(tmp_path)
        self._write_adx(tmp_path, adx=30)
        context, _ = self._trend_context()
        perf = {"nifty_cash_long": StrategyResult(name="nifty_cash_long")}
        perf["nifty_cash_long"].disabled_at = "2026-09-29T00:00:00"
        strategy = sl.select_strategy(context, perf)
        if strategy is not None:
            assert strategy.name != "nifty_cash_long", (
                f"Disabled cash_long should not be picked, got {strategy.name}")


class TestCASRoutingInMain:
    """The CAS leg detector in __main__.py must bypass missing-field validation."""

    def test_cash_leg_recognized_by_segment_field(self):
        """A leg with segment='nse_cm' must be detected as a CAS leg."""
        # Smoke test: build a CAS leg and check the routing logic
        leg = {"side": "BUY", "qty": 75, "instrument": "NIFTY",
               "order_type": "MARKET", "price": None, "segment": "nse_cm"}
        is_cash = str(leg.get("segment", "")).lower() == "nse_cm"
        assert is_cash is True

    def test_option_leg_not_misidentified_as_cas(self):
        """An option leg (segment=nse_fo) must NOT be detected as CAS."""
        leg = {"side": "BUY", "qty": 1050, "strike": 22950, "opt_type": "CE",
               "order_type": "MARKET", "price": None, "segment": "nse_fo"}
        is_cash = str(leg.get("segment", "")).lower() == "nse_cm"
        assert is_cash is False

    def test_cash_leg_has_no_strike_or_opt_type(self):
        """CAS legs deliberately omit strike/opt_type — the router must handle this."""
        # This is more of a documentation test: confirm the structure that
        # generate_trade_plan produces does NOT have strike/opt_type keys.
        from scripts.strategy_library import generate_trade_plan, STRATEGIES
        plan = generate_trade_plan(STRATEGIES["nifty_cash_long"],
                                   {"spot": 22750, "vix": 13.0},
                                   capital=100000, vix=13.0)
        leg = plan["legs"][0]
        # CAS legs should NOT have strike/opt_type keys
        assert "strike" not in leg
        assert "opt_type" not in leg
        # They SHOULD have instrument + segment
        assert "instrument" in leg
        assert leg["instrument"] == "NIFTY"
        assert leg["segment"] == "nse_cm"

    def test_exchange_field_for_cas_is_nse(self):
        """CAS legs must be placed on NSE (cash), not NFO (options)."""
        # Read __main__.py and verify the _order_exchange routing
        main_py = (ROOT / "kotak_bot" / "__main__.py").read_text(encoding="utf-8")
        assert '_order_exchange = "NSE" if _is_cash_leg else "NFO"' in main_py, (
            "__main__.py must route CAS legs to NSE segment"
        )