"""Black-Scholes option Greeks — delta, gamma, vega, theta, rho.

Pure-Python implementation, no external dependencies (no scipy). Uses the
standard normal CDF and PDF computed via the error function (math.erf).

For NSE index options (NIFTY, BANKNIFTY), Black-Scholes is the de-facto
model — exchanges don't publish their own vol surface, and the BSE/NSE
volatility index (India VIX) is calibrated to a 30-day BS-like model.

The Greeks here are used for:
  - Risk management: how much will the position move if spot moves 1%?
  - Position sizing: how many contracts to keep delta-neutral?
  - Exit logic: did theta decay kill the trade's edge?
  - Mark-to-market with bid/ask spread (using delta to estimate fair value
    after a 1-tick move).

Conventions:
  - All inputs are in YEARS (e.g. 7 days = 7/365)
  - All outputs are per-unit (multiply by qty * lot_size for portfolio impact)
  - r = risk-free rate (default 6.5%, near current Indian 10Y G-Sec)
  - q = dividend yield (NIFTY: ~1.5%, BANKNIFTY: ~0%)
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal


SQRT_2PI = math.sqrt(2.0 * math.pi)


def _norm_cdf(x: float) -> float:
    """Standard normal CDF using math.erf."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    """Standard normal PDF."""
    return math.exp(-0.5 * x * x) / SQRT_2PI


@dataclass
class Greeks:
    """All first- and second-order Greeks for a single option contract."""
    delta: float = 0.0
    gamma: float = 0.0
    vega: float = 0.0       # per 1% change in IV
    theta: float = 0.0      # per day
    rho: float = 0.0        # per 1% change in r
    price: float = 0.0      # theoretical price
    d1: float = 0.0
    d2: float = 0.0

    def to_dict(self) -> dict:
        return {
            "delta": round(self.delta, 6),
            "gamma": round(self.gamma, 6),
            "vega": round(self.vega, 6),
            "theta": round(self.theta, 6),
            "rho": round(self.rho, 6),
            "price": round(self.price, 4),
        }


def bs_greeks(
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    vol: float,
    r: float = 0.065,
    q: float = 0.0,
    option_type: Literal["CE", "PE", "C", "P"] = "CE",
) -> Greeks:
    """Compute Black-Scholes Greeks for a European option.

    Args:
        spot: current underlying price (e.g. 24276.20 for NIFTY)
        strike: option strike price
        time_to_expiry_years: T in years (e.g. 7/365 for 7-day option)
        vol: annualized implied volatility (e.g. 0.15 for 15%)
        r: risk-free rate (annualized)
        q: continuous dividend yield (annualized)
        option_type: 'CE' / 'PE' or 'C' / 'P'

    Returns:
        Greeks dataclass with delta, gamma, vega, theta, rho, price
    """
    if vol <= 0 or time_to_expiry_years <= 0 or spot <= 0 or strike <= 0:
        # Edge case: at expiry or invalid inputs — return intrinsic-only values
        if option_type.upper().startswith("C"):
            return Greeks(delta=1.0 if spot > strike else 0.0,
                          price=max(0.0, spot - strike))
        else:
            return Greeks(delta=-1.0 if spot < strike else 0.0,
                          price=max(0.0, strike - spot))

    sqrt_t = math.sqrt(time_to_expiry_years)
    # Avoid div-by-zero if vol is degenerate
    sigma_sqrt_t = vol * sqrt_t
    if sigma_sqrt_t == 0:
        sigma_sqrt_t = 1e-9
    log_moneyness = math.log(spot / strike)
    d1 = (log_moneyness + (r - q + 0.5 * vol * vol) * time_to_expiry_years) / sigma_sqrt_t
    d2 = d1 - sigma_sqrt_t

    is_call = option_type.upper().startswith("C")
    if is_call:
        price = (spot * math.exp(-q * time_to_expiry_years) * _norm_cdf(d1)
                 - strike * math.exp(-r * time_to_expiry_years) * _norm_cdf(d2))
        delta = math.exp(-q * time_to_expiry_years) * _norm_cdf(d1)
        theta = (
            -(spot * _norm_pdf(d1) * vol * math.exp(-q * time_to_expiry_years)) / (2.0 * sqrt_t)
            - r * strike * math.exp(-r * time_to_expiry_years) * _norm_cdf(d2)
            + q * spot * math.exp(-q * time_to_expiry_years) * _norm_cdf(d1)
        ) / 365.0  # per-day
        rho = (strike * time_to_expiry_years * math.exp(-r * time_to_expiry_years) * _norm_cdf(d2)) / 100.0
    else:
        price = (strike * math.exp(-r * time_to_expiry_years) * _norm_cdf(-d2)
                 - spot * math.exp(-q * time_to_expiry_years) * _norm_cdf(-d1))
        delta = -math.exp(-q * time_to_expiry_years) * _norm_cdf(-d1)
        theta = (
            -(spot * _norm_pdf(d1) * vol * math.exp(-q * time_to_expiry_years)) / (2.0 * sqrt_t)
            + r * strike * math.exp(-r * time_to_expiry_years) * _norm_cdf(-d2)
            - q * spot * math.exp(-q * time_to_expiry_years) * _norm_cdf(-d1)
        ) / 365.0  # per-day
        rho = (-strike * time_to_expiry_years * math.exp(-r * time_to_expiry_years) * _norm_cdf(-d2)) / 100.0

    gamma = (math.exp(-q * time_to_expiry_years) * _norm_pdf(d1)) / (spot * sigma_sqrt_t)
    # Vega per 1% change in IV (so divide by 100)
    vega = (spot * math.exp(-q * time_to_expiry_years) * _norm_pdf(d1) * sqrt_t) / 100.0

    return Greeks(
        delta=delta, gamma=gamma, vega=vega, theta=theta, rho=rho,
        price=max(0.0, price), d1=d1, d2=d2,
    )


def portfolio_greeks(legs: list[dict], spot: float, r: float = 0.065, q: float = 0.0) -> Greeks:
    """Aggregate Greeks across a multi-leg position.

    Each leg dict must have:
      strike, opt_type ('CE'/'PE'), qty, avg_fill_price (for IV estimation)
    Optional: days_to_expiry (default 7), iv_override (default = computed from market)
    """
    total = Greeks()
    for leg in legs:
        strike = float(leg.get("strike", 0))
        opt = leg.get("opt_type", "CE")
        qty = int(leg.get("qty", 0))  # positive for long, negative for short
        days = float(leg.get("days_to_expiry", 7))
        t = max(1e-6, days / 365.0)
        # Estimate IV from fill price vs BS price (a simple bisection)
        fill = float(leg.get("avg_fill_price", 0) or 0)
        iv = float(leg.get("iv_override", 0) or 0)
        if iv <= 0 and fill > 0 and spot > 0 and strike > 0:
            iv = _implied_vol(spot, strike, t, fill, r, q, opt)
        iv = max(0.05, min(2.0, iv or 0.20))  # clamp 5%–200%
        g = bs_greeks(spot, strike, t, iv, r, q, opt)
        # Sign convention: short position (qty < 0) flips greeks
        sign = 1.0 if qty > 0 else -1.0
        abs_qty = abs(qty)
        total.delta += sign * g.delta * abs_qty
        total.gamma += sign * g.gamma * abs_qty
        total.vega += sign * g.vega * abs_qty
        total.theta += sign * g.theta * abs_qty
        total.rho += sign * g.rho * abs_qty
        total.price += sign * g.price * abs_qty
    return total


def _implied_vol(
    spot: float,
    strike: float,
    t: float,
    market_price: float,
    r: float,
    q: float,
    option_type: str,
    tol: float = 1e-4,
    max_iter: int = 50,
) -> float:
    """Bisection IV solver. Returns annualized vol (e.g. 0.15 for 15%)."""
    lo, hi = 0.01, 3.0
    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        g = bs_greeks(spot, strike, t, mid, r, q, option_type)
        diff = g.price - market_price
        if abs(diff) < tol:
            return mid
        # If model price > market, vol is too high → lower it
        if diff > 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2.0


def mark_to_market(
    leg: dict,
    spot: float,
    bid: float,
    ask: float,
    r: float = 0.065,
    q: float = 0.0,
) -> dict:
    """Mark a leg to market using the conservative side of the bid/ask spread.

    Long positions are marked at BID (what you'd get if you sold to close).
    Short positions are marked at ASK (what you'd pay to buy to close).

    Returns:
        dict with: theoretical_price, bid, ask, mtm_price, mtm_pnl, mid_spread_bps
    """
    strike = float(leg.get("strike", 0))
    opt = leg.get("opt_type", "CE")
    qty = int(leg.get("qty", 0))
    fill = float(leg.get("avg_fill_price", 0) or 0)
    days = float(leg.get("days_to_expiry", 7))
    t = max(1e-6, days / 365.0)
    if fill > 0 and spot > 0 and strike > 0:
        iv = _implied_vol(spot, strike, t, fill, r, q, opt)
    else:
        iv = 0.20
    g = bs_greeks(spot, strike, t, iv, r, q, opt)
    # Use the broker's bid/ask if both > 0; otherwise fall back to theoretical
    if bid > 0 and ask > 0:
        is_long = qty > 0
        mtm_unit = bid if is_long else ask
    else:
        mtm_unit = g.price
    mid = (bid + ask) / 2 if (bid > 0 and ask > 0) else g.price
    spread_bps = ((ask - bid) / mid * 10000) if (mid > 0 and ask > 0 and bid > 0) else 0.0
    # P&L per unit = mtm - fill (sign-aware)
    pnl_per_unit = mtm_unit - fill
    sign = 1.0 if qty > 0 else -1.0
    pnl = pnl_per_unit * abs(qty) * sign
    return {
        "theoretical_price": round(g.price, 4),
        "iv": round(iv, 4),
        "bid": bid,
        "ask": ask,
        "mtm_price": round(mtm_unit, 4),
        "mtm_pnl": round(pnl, 2),
        "mid_spread_bps": round(spread_bps, 1),
        "delta": round(g.delta, 4),
    }
