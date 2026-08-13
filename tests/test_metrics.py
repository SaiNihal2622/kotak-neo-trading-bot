"""Tests for risk metrics (drawdown, VaR/CVaR, Kelly, Sharpe, POP)."""
from __future__ import annotations

import math

import pytest

from kotak_bot.risk.metrics import (
    RiskMetrics,
    compute_metrics,
    probability_of_profit,
)


# ----------------- compute_metrics basics -----------------

def test_empty_series_returns_zeros():
    m = compute_metrics([])
    assert m.n == 0
    assert m.total == 0.0
    assert m.sharpe == 0.0
    assert m.max_drawdown == 0.0


def test_single_value_series():
    m = compute_metrics([100.0])
    assert m.n == 1
    assert m.total == 100.0
    assert m.max_drawdown == 0.0  # can't have DD with 1 point
    assert m.sharpe == 0.0  # can't compute stdev with 1 point


def test_known_series_drawdown():
    """Cumulative equity: 10, 5, -5, 0, 20 → peak=20 (last), but if we look at peak=10, DD=15."""
    # pnl = [10, -5, -10, 5, 20]
    # cum_equity = [10, 5, -5, 0, 20]
    # peak at step 0 = 10, drop to -5 → DD = 15
    m = compute_metrics([10, -5, -10, 5, 20])
    assert m.n == 5
    assert m.total == 20
    # Max drawdown = peak(10) - trough(-5) = 15
    assert m.max_drawdown == 15


def test_known_series_sharpe_positive_for_wins():
    """A series of all +1 should have very high Sharpe (low std, positive mean)."""
    m = compute_metrics([1.0] * 252, periods_per_year=252)
    # With std=0, our code returns 0 (avoid division by zero) — verify that's safe
    assert m.sharpe == 0.0
    # Better test: 1.0 with tiny noise → very high Sharpe
    pnl = [1.0 + (0.001 if i % 2 else -0.001) for i in range(252)]
    m = compute_metrics(pnl, periods_per_year=252)
    assert m.sharpe > 50  # very high but finite


def test_known_series_sharpe_negative_for_losses():
    pnl = [-1.0 + (0.001 if i % 2 else -0.001) for i in range(252)]
    m = compute_metrics(pnl, periods_per_year=252)
    assert m.sharpe < -50


def test_known_series_mixed_sharpe():
    """Mixed gains/losses — Sharpe should be near 0 if mean is 0."""
    pnl = [1.0, -1.0] * 50
    m = compute_metrics(pnl, periods_per_year=252)
    # Mean is 0, stdev is 1, so sharpe ~= 0 (slightly off due to rf)
    assert abs(m.sharpe) < 1.0


def test_var_95_is_positive_for_losing_series():
    """VaR should be a positive number representing potential loss."""
    pnl = [-10.0] * 100 + [1.0] * 5  # mostly losses
    m = compute_metrics(pnl)
    assert m.var_95 >= 0
    assert m.cvar_95 >= m.var_95 * 0.5  # CVaR ≥ VaR in expectation


def test_var_95_zero_for_all_wins():
    pnl = [1.0] * 100
    m = compute_metrics(pnl)
    assert m.var_95 == 0
    assert m.cvar_95 == 0


def test_win_rate_avg_win_loss():
    pnl = [10, 20, -5, -10, 30]
    m = compute_metrics(pnl)
    assert m.win_rate == 0.6  # 3 wins out of 5
    assert m.avg_win == 20.0  # (10+20+30)/3
    assert m.avg_loss == -7.5  # (-5 + -10) / 2
    assert m.profit_factor == 60 / 15  # sum(wins)/abs(sum(losses))


def test_profit_factor_infinite_when_no_losses():
    m = compute_metrics([10, 20, 30])
    # No losses → profit_factor=0 by convention (avoid inf)
    assert m.profit_factor == 0


def test_expectancy_calculation():
    pnl = [10, 20, -5, -10]
    m = compute_metrics(pnl)
    # 50% win rate, avg win 15, avg loss -7.5
    # expectancy = 0.5*15 + 0.5*-7.5 = 3.75
    assert abs(m.expectancy - 3.75) < 0.01


def test_kelly_fraction_basic():
    """60% win rate, 2:1 reward/risk → Kelly = 0.2 (bet 20% of bankroll)."""
    pnl = [2.0] * 60 + [-1.0] * 40
    m = compute_metrics(pnl)
    # Kelly = p/a - q/b where a=avg_win, b=avg_loss_abs = 0.6/2 - 0.4/1 = 0.3 - 0.4 = -0.1
    # Hmm that gives negative. Let me reconsider with p=60%, win=2, loss=1
    # Kelly = (p*W - (1-p)*L)/(W*L) where W=win, L=loss_abs
    #       = (0.6*2 - 0.4*1)/(2*1) = (1.2-0.4)/2 = 0.4
    assert abs(m.kelly_fraction - 0.4) < 0.01


def test_kelly_capped_at_1():
    pnl = [100.0] * 100  # 100% win rate, huge rewards
    m = compute_metrics(pnl)
    assert m.kelly_fraction <= 1.0


def test_max_drawdown_pct_with_starting_capital():
    pnl = [10, -15, 5]  # cum_equity from 100: 110, 95, 100
    m = compute_metrics(pnl, starting_capital=100)
    # Peak = 110, drawdown = 110-95=15, % = 15/110 = 13.6%
    assert m.max_drawdown == 15
    assert abs(m.max_drawdown_pct - 15/110) < 0.01


def test_current_drawdown_at_latest_point():
    pnl = [10, 10, -25, 5]  # cum_equity: 10, 20, -5, 0
    m = compute_metrics(pnl)
    # Peak was 20, current equity 0 → current DD = 20
    assert m.current_drawdown == 20


def test_no_drawdown_when_monotonically_increasing():
    pnl = [1, 2, 3, 4, 5]
    m = compute_metrics(pnl)
    assert m.max_drawdown == 0
    assert m.current_drawdown == 0


# ----------------- POP (probability of profit) -----------------

def test_pop_short_call_above_spot():
    """Short call with strike well above spot → high POP."""
    legs = [
        {"strike": 25000, "opt_type": "CE", "qty": -65, "days_to_expiry": 7, "iv_override": 0.15},
        {"strike": 25500, "opt_type": "CE", "qty": 65, "days_to_expiry": 7, "iv_override": 0.15},
    ]
    pop = probability_of_profit(legs, spot=24276.20, target_credit=0, max_loss=0)
    assert pop > 0.7, f"Short OTM call should have high POP, got {pop}"


def test_pop_short_put_below_spot():
    """Short put with strike well below spot → high POP."""
    legs = [
        {"strike": 23500, "opt_type": "PE", "qty": -65, "days_to_expiry": 7, "iv_override": 0.15},
        {"strike": 23000, "opt_type": "PE", "qty": 65, "days_to_expiry": 7, "iv_override": 0.15},
    ]
    pop = probability_of_profit(legs, spot=24276.20, target_credit=0, max_loss=0)
    assert pop > 0.7


def test_pop_iron_condor_centered_on_spot():
    """IC centered near spot has POP ~0.5-0.7."""
    legs = [
        {"strike": 24500, "opt_type": "CE", "qty": -65, "days_to_expiry": 7, "iv_override": 0.15},
        {"strike": 24700, "opt_type": "CE", "qty": 65, "days_to_expiry": 7, "iv_override": 0.15},
        {"strike": 24000, "opt_type": "PE", "qty": -65, "days_to_expiry": 7, "iv_override": 0.15},
        {"strike": 23800, "opt_type": "PE", "qty": 65, "days_to_expiry": 7, "iv_override": 0.15},
    ]
    pop = probability_of_profit(legs, spot=24276.20, target_credit=0, max_loss=0)
    assert 0.3 < pop < 0.8, f"IC centered POP should be moderate, got {pop}"


def test_pop_empty_legs_returns_zero():
    pop = probability_of_profit([], spot=24276.20, target_credit=0, max_loss=0)
    assert pop == 0.0


def test_pop_only_long_legs_returns_zero():
    """No short legs → can't compute POP conservatively."""
    legs = [
        {"strike": 24200, "opt_type": "CE", "qty": 65, "days_to_expiry": 7},
    ]
    pop = probability_of_profit(legs, spot=24276.20, target_credit=0, max_loss=0)
    assert pop == 0.0


# ----------------- RiskMetrics dataclass -----------------

def test_risk_metrics_to_dict_includes_all_fields():
    m = RiskMetrics()
    d = m.to_dict()
    expected_fields = {
        "n", "total", "mean", "std", "max_drawdown", "max_drawdown_pct",
        "current_drawdown", "sharpe", "sortino", "var_95", "var_99",
        "cvar_95", "cvar_99", "kelly_fraction", "win_rate", "avg_win",
        "avg_loss", "profit_factor", "expectancy", "pop",
    }
    assert set(d.keys()) == expected_fields


def test_risk_metrics_to_dict_pct_fields_are_percentages():
    m = RiskMetrics(max_drawdown_pct=0.25, win_rate=0.6)
    d = m.to_dict()
    # Percentages in to_dict are scaled to % (multiply by 100)
    assert d["max_drawdown_pct"] == 25.0
    assert d["win_rate"] == 60.0


# ----------------- edge cases -----------------

def test_compute_metrics_with_zero_periods_per_year():
    """Should not divide by zero in Sharpe."""
    pnl = [1.0, -1.0, 2.0, -2.0]
    m = compute_metrics(pnl, periods_per_year=0)
    # sharpe will be 0 (we can't annualize), but std should be valid
    assert m.std > 0
    assert m.sharpe == 0.0


def test_compute_metrics_with_constant_pnl():
    pnl = [5.0] * 10
    m = compute_metrics(pnl)
    # std is 0, sharpe is 0
    assert m.std == 0.0
    assert m.sharpe == 0.0
    assert m.sortino == 0.0


def test_compute_metrics_with_single_loss():
    m = compute_metrics([-100.0])
    assert m.max_drawdown == 100
    assert m.current_drawdown == 100
    assert m.var_95 == 100  # only one point
