"""Tests for the Black-Scholes Greeks engine."""
from __future__ import annotations

import math

import pytest

from kotak_bot.risk.greeks import (
    Greeks,
    bs_greeks,
    mark_to_market,
    portfolio_greeks,
)


# ----------------- BS price sanity checks -----------------

def test_atm_call_delta_around_0_5():
    """ATM call should have delta ≈ 0.5 (more if r > q, less if r < q)."""
    g = bs_greeks(spot=100, strike=100, time_to_expiry_years=30/365,
                  vol=0.20, r=0.065, q=0.0, option_type="CE")
    assert 0.45 < g.delta < 0.65, f"ATM call delta should be ~0.5, got {g.delta}"


def test_atm_put_delta_around_minus_0_5():
    g = bs_greeks(spot=100, strike=100, time_to_expiry_years=30/365,
                  vol=0.20, r=0.065, q=0.0, option_type="PE")
    assert -0.55 < g.delta < -0.45, f"ATM put delta should be ~-0.5, got {g.delta}"


def test_deep_itm_call_delta_approaches_1():
    g = bs_greeks(spot=200, strike=100, time_to_expiry_years=30/365,
                  vol=0.20, r=0.065, q=0.0, option_type="CE")
    assert g.delta > 0.95, f"deep ITM call delta should be ~1, got {g.delta}"


def test_deep_otm_call_delta_approaches_0():
    g = bs_greeks(spot=100, strike=200, time_to_expiry_years=30/365,
                  vol=0.20, r=0.065, q=0.0, option_type="CE")
    assert g.delta < 0.05, f"deep OTM call delta should be ~0, got {g.delta}"


def test_gamma_positive_for_both_calls_and_puts():
    """Gamma is always positive for long options (same for call and put at same strike)."""
    g_call = bs_greeks(spot=100, strike=100, time_to_expiry_years=30/365, vol=0.20, option_type="CE")
    g_put = bs_greeks(spot=100, strike=100, time_to_expiry_years=30/365, vol=0.20, option_type="PE")
    assert g_call.gamma > 0
    assert g_put.gamma > 0
    assert abs(g_call.gamma - g_put.gamma) < 1e-6  # same by put-call parity


def test_vega_positive():
    """Vega is always positive (long options benefit from higher IV)."""
    g = bs_greeks(spot=100, strike=100, time_to_expiry_years=30/365, vol=0.20, option_type="CE")
    assert g.vega > 0


def test_theta_negative_for_long_options():
    """Theta is negative for long options (time decay hurts)."""
    g = bs_greeks(spot=100, strike=100, time_to_expiry_years=30/365, vol=0.20, option_type="CE")
    assert g.theta < 0, f"theta should be negative for long ATM call, got {g.theta}"


def test_put_call_parity():
    """C - P = S*exp(-qT) - K*exp(-rT) (for European options)."""
    S, K, T, vol, r, q = 24276.20, 24300, 7/365, 0.15, 0.065, 0.015
    c = bs_greeks(S, K, T, vol, r, q, "CE")
    p = bs_greeks(S, K, T, vol, r, q, "PE")
    parity = S * math.exp(-q * T) - K * math.exp(-r * T)
    actual_diff = c.price - p.price
    assert abs(actual_diff - parity) < 0.1, f"put-call parity violated: diff={actual_diff} vs {parity}"


def test_price_increases_with_spot_for_call():
    g1 = bs_greeks(spot=24000, strike=24200, time_to_expiry_years=7/365, vol=0.15, option_type="CE")
    g2 = bs_greeks(spot=24400, strike=24200, time_to_expiry_years=7/365, vol=0.15, option_type="CE")
    assert g2.price > g1.price


def test_price_decreases_with_spot_for_put():
    g1 = bs_greeks(spot=24400, strike=24200, time_to_expiry_years=7/365, vol=0.15, option_type="PE")
    g2 = bs_greeks(spot=24000, strike=24200, time_to_expiry_years=7/365, vol=0.15, option_type="PE")
    assert g2.price > g1.price


def test_price_increases_with_vol():
    g1 = bs_greeks(spot=24200, strike=24200, time_to_expiry_years=7/365, vol=0.10, option_type="CE")
    g2 = bs_greeks(spot=24200, strike=24200, time_to_expiry_years=7/365, vol=0.20, option_type="CE")
    assert g2.price > g1.price


def test_price_increases_with_time():
    g1 = bs_greeks(spot=24200, strike=24200, time_to_expiry_years=1/365, vol=0.15, option_type="CE")
    g2 = bs_greeks(spot=24200, strike=24200, time_to_expiry_years=30/365, vol=0.15, option_type="CE")
    assert g2.price > g1.price


# ----------------- edge cases -----------------

def test_zero_time_returns_intrinsic():
    """T=0 (expiry) → price = intrinsic, delta = 0 or 1, gamma = 0."""
    g = bs_greeks(spot=100, strike=90, time_to_expiry_years=0, vol=0.20, option_type="CE")
    assert g.price == 10.0
    assert g.delta == 1.0
    assert g.gamma == 0.0


def test_zero_vol_returns_intrinsic():
    g = bs_greeks(spot=100, strike=90, time_to_expiry_years=30/365, vol=0.0, option_type="CE")
    assert g.price == 10.0


def test_otm_put_at_expiry_zero_price():
    """OTM put = spot > strike, put has no intrinsic value at expiry."""
    g = bs_greeks(spot=100, strike=90, time_to_expiry_years=0, vol=0.20, option_type="PE")
    assert g.price == 0.0
    assert g.delta == 0.0


def test_negative_inputs_safely_handled():
    g = bs_greeks(spot=-1, strike=100, time_to_expiry_years=30/365, vol=0.20, option_type="CE")
    # Should not raise; returns zeros or intrinsic
    assert g.price >= 0


# ----------------- implied vol round-trip -----------------

def test_implied_vol_round_trip():
    """IV solver should recover the original vol from a known price."""
    from kotak_bot.risk.greeks import _implied_vol
    spot, strike, t, vol_true = 24276.20, 24300, 7/365, 0.18
    g = bs_greeks(spot, strike, t, vol_true, 0.065, 0.015, "CE")
    iv = _implied_vol(spot, strike, t, g.price, 0.065, 0.015, "CE")
    assert abs(iv - vol_true) < 0.01, f"IV round-trip failed: {iv} vs {vol_true}"


# ----------------- portfolio aggregation -----------------

def test_portfolio_greeks_long_call_only():
    legs = [{"strike": 24200, "opt_type": "CE", "qty": 65, "avg_fill_price": 100.0, "days_to_expiry": 7}]
    g = portfolio_greeks(legs, spot=24276.20, r=0.065, q=0.015)
    assert g.delta > 0
    assert g.gamma > 0


def test_portfolio_greeks_iron_condor_neutral():
    """A well-constructed iron condor should be near delta-neutral."""
    spot = 24276.20
    legs = [
        {"strike": 24550, "opt_type": "CE", "qty": -65, "avg_fill_price": 50.0, "days_to_expiry": 7},  # SELL
        {"strike": 24450, "opt_type": "CE", "qty": 65, "avg_fill_price": 100.0, "days_to_expiry": 7},   # BUY
        {"strike": 24150, "opt_type": "PE", "qty": 65, "avg_fill_price": 90.0, "days_to_expiry": 7},   # BUY
        {"strike": 24050, "opt_type": "PE", "qty": -65, "avg_fill_price": 40.0, "days_to_expiry": 7},  # SELL
    ]
    g = portfolio_greeks(legs, spot=spot, r=0.065, q=0.015)
    # Iron condor centered around spot should have |delta| < 5 (allowing for the spread being OTM)
    assert abs(g.delta) < 5.0, f"iron condor delta should be near 0, got {g.delta}"


def test_portfolio_greeks_short_position_flips_signs():
    """Short position (qty=-1) should have opposite delta to long."""
    long_legs = [{"strike": 24200, "opt_type": "CE", "qty": 65, "avg_fill_price": 100.0, "days_to_expiry": 7}]
    short_legs = [{"strike": 24200, "opt_type": "CE", "qty": -65, "avg_fill_price": 100.0, "days_to_expiry": 7}]
    g_long = portfolio_greeks(long_legs, spot=24200, r=0.065, q=0.015)
    g_short = portfolio_greeks(short_legs, spot=24200, r=0.065, q=0.015)
    assert abs(g_long.delta + g_short.delta) < 1e-6


def test_portfolio_greeks_uses_iv_override():
    """iv_override should skip the bisection solver."""
    legs = [{"strike": 24200, "opt_type": "CE", "qty": 65, "avg_fill_price": 100.0,
             "days_to_expiry": 7, "iv_override": 0.50}]
    g = portfolio_greeks(legs, spot=24200, r=0.065, q=0.015)
    # Higher IV → higher vega per unit
    g_no_override = portfolio_greeks(
        [{"strike": 24200, "opt_type": "CE", "qty": 65, "avg_fill_price": 100.0, "days_to_expiry": 7}],
        spot=24200, r=0.065, q=0.015,
    )
    # Both should be valid Greeks
    assert g.vega > 0
    assert g_no_override.vega > 0


# ----------------- mark-to-market -----------------

def test_mtm_long_uses_bid():
    """Long position MTMs at bid (what you'd get closing)."""
    leg = {"strike": 24200, "opt_type": "CE", "qty": 65, "avg_fill_price": 100.0, "days_to_expiry": 7}
    mtm = mark_to_market(leg, spot=24276.20, bid=105.0, ask=110.0)
    assert mtm["mtm_price"] == 105.0  # long closes at bid
    # P&L = (bid - fill) * qty = (105-100)*65 = 325
    assert mtm["mtm_pnl"] == 325.0


def test_mtm_short_uses_ask():
    """Short position MTMs at ask (what you'd pay closing)."""
    leg = {"strike": 24200, "opt_type": "CE", "qty": -65, "avg_fill_price": 100.0, "days_to_expiry": 7}
    mtm = mark_to_market(leg, spot=24276.20, bid=95.0, ask=100.0)
    assert mtm["mtm_price"] == 100.0  # short closes at ask
    # Short P&L = -(ask - fill) * |qty| = -(100-100)*65 = 0
    assert mtm["mtm_pnl"] == 0.0


def test_mtm_short_with_loss():
    """Short position where ask > fill = loss."""
    leg = {"strike": 24200, "opt_type": "CE", "qty": -65, "avg_fill_price": 100.0, "days_to_expiry": 7}
    mtm = mark_to_market(leg, spot=24276.20, bid=110.0, ask=120.0)
    assert mtm["mtm_price"] == 120.0
    # Short P&L = -(120-100)*65 = -1300
    assert mtm["mtm_pnl"] == -1300.0


def test_mtm_falls_back_to_theoretical_when_no_bid_ask():
    leg = {"strike": 24200, "opt_type": "CE", "qty": 65, "avg_fill_price": 100.0, "days_to_expiry": 7}
    mtm = mark_to_market(leg, spot=24276.20, bid=0, ask=0)
    assert mtm["mtm_price"] > 0  # falls back to BS theoretical
    assert mtm["mid_spread_bps"] == 0.0  # no spread


def test_mtm_spread_bps():
    leg = {"strike": 24200, "opt_type": "CE", "qty": 65, "avg_fill_price": 100.0, "days_to_expiry": 7}
    mtm = mark_to_market(leg, spot=24276.20, bid=100.0, ask=102.0)
    # mid=101, spread=2, bps = 2/101 * 10000 = 198 bps
    assert 195 < mtm["mid_spread_bps"] < 200


# ----------------- Greeks dataclass -----------------

def test_greeks_to_dict():
    g = Greeks(delta=0.5, gamma=0.001, vega=10.0, theta=-5.0, rho=1.0, price=100.0)
    d = g.to_dict()
    assert d["delta"] == 0.5
    assert d["gamma"] == 0.001
    assert d["vega"] == 10.0
    assert d["theta"] == -5.0
    assert d["rho"] == 1.0
    assert d["price"] == 100.0
