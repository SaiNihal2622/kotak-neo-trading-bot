"""Option Greeks calculator using Black-Scholes.

Used by quant brain for risk management, position sizing, and IV analysis.
Pure-stdlib, no numpy/scipy dependency (we implement BS ourselves with math.erf).

Conventions:
- All rates are annualized
- Time to expiry in years
- IV expressed as 0.20 = 20%
- Greeks per share (multiply by lot size for position-level)
"""
from __future__ import annotations
import math
from typing import Optional


SQRT_2PI = math.sqrt(2.0 * math.pi)


def _norm_cdf(x: float) -> float:
    """Standard normal CDF using math.erf (avoids scipy dependency)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    """Standard normal PDF."""
    return math.exp(-0.5 * x * x) / SQRT_2PI


def _d1_d2(spot: float, strike: float, t_years: float, r: float, sigma: float):
    """Black-Scholes d1 and d2."""
    if t_years <= 0 or sigma <= 0 or spot <= 0 or strike <= 0:
        return None, None
    sigma_sqrt_t = sigma * math.sqrt(t_years)
    d1 = (math.log(spot / strike) + (r + 0.5 * sigma * sigma) * t_years) / sigma_sqrt_t
    d2 = d1 - sigma_sqrt_t
    return d1, d2


def bs_price(spot: float, strike: float, t_years: float, r: float, sigma: float, option_type: str) -> Optional[float]:
    """Black-Scholes option price. Returns None if inputs invalid."""
    d1, d2 = _d1_d2(spot, strike, t_years, r, sigma)
    if d1 is None:
        return None
    if option_type.upper() == "CE":
        return spot * _norm_cdf(d1) - strike * math.exp(-r * t_years) * _norm_cdf(d2)
    elif option_type.upper() == "PE":
        return strike * math.exp(-r * t_years) * _norm_cdf(-d2) - spot * _norm_cdf(-d1)
    return None


def greeks(spot: float, strike: float, t_years: float, r: float, sigma: float, option_type: str) -> Optional[dict]:
    """Compute option greeks. Returns dict with delta, gamma, theta, vega, rho per share.

    Theta is in PER YEAR. Divide by 365 for per-day, by 252 for per-trading-day.
    Vega is per 1.0 (=100%) IV change. Divide by 100 for per-1% IV.
    Rho is per 1.0 (=100%) rate change.
    """
    d1, d2 = _d1_d2(spot, strike, t_years, r, sigma)
    if d1 is None:
        return None
    nd1 = _norm_cdf(d1)
    nd2 = _norm_cdf(d2)
    pdf_d1 = _norm_pdf(d1)

    if option_type.upper() == "CE":
        delta = nd1
        theta = (-spot * pdf_d1 * sigma / (2.0 * math.sqrt(t_years))
                 - r * strike * math.exp(-r * t_years) * nd2)
        rho = strike * t_years * math.exp(-r * t_years) * nd2
    elif option_type.upper() == "PE":
        delta = nd1 - 1.0
        theta = (-spot * pdf_d1 * sigma / (2.0 * math.sqrt(t_years))
                 + r * strike * math.exp(-r * t_years) * _norm_cdf(-d2))
        rho = -strike * t_years * math.exp(-r * t_years) * _norm_cdf(-d2)
    else:
        return None

    gamma = pdf_d1 / (spot * sigma * math.sqrt(t_years))
    vega = spot * pdf_d1 * math.sqrt(t_years)

    return {
        "delta": delta,
        "gamma": gamma,
        "theta": theta,  # per year
        "vega": vega,    # per 1.0 IV
        "rho": rho,      # per 1.0 rate
    }


def iv_from_price(market_price: float, spot: float, strike: float, t_years: float, r: float, option_type: str,
                  tol: float = 1e-5, max_iter: int = 50) -> Optional[float]:
    """Implied volatility via Newton-Raphson.

    Given an observed market price, find sigma such that BS(market_price) = sigma-implied price.
    Returns IV as decimal (0.20 = 20%) or None if not converging.
    """
    if market_price <= 0 or spot <= 0 or strike <= 0 or t_years <= 0:
        return None
    sigma = 0.30  # initial guess
    for _ in range(max_iter):
        price = bs_price(spot, strike, t_years, r, sigma, option_type)
        if price is None:
            return None
        diff = price - market_price
        if abs(diff) < tol:
            return sigma
        g = greeks(spot, strike, t_years, r, sigma, option_type)
        if g is None or g["vega"] == 0:
            return None
        sigma = sigma - diff / g["vega"]
        if sigma <= 0:
            sigma = 0.01
    return None  # didn't converge


def position_greeks(legs: list, spot: float, r: float, sigma: float, t_years: float) -> dict:
    """Compute position-level greeks by aggregating per-leg.

    Each leg: {"side": "BUY"|"SELL", "qty": int (lots), "strike": int, "opt_type": "CE"|"PE"}
    sigma: same IV applied to all legs (use per-leg IV for skew, but single IV is OK for fast calc)

    Returns: {"delta": float, "gamma": float, "theta": float, "vega": float, "rho": float, "notional": float}
    All greeks are total (multiplied by lot size and signed by side).
    """
    lot_sizes = {"NIFTY": 75, "BANKNIFTY": 30, "FINNIFTY": 65, "MIDCPNIFTY": 120}
    out = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0, "notional": 0.0}
    for leg in legs:
        underlying = leg.get("underlying", "NIFTY")
        lot = lot_sizes.get(underlying.upper(), 75)
        qty_shares = leg["qty"] * lot
        sign = 1 if leg["side"].upper() == "BUY" else -1
        g = greeks(spot, leg["strike"], t_years, r, sigma, leg["opt_type"])
        if g is None:
            continue
        out["delta"] += sign * qty_shares * g["delta"]
        out["gamma"] += sign * qty_shares * g["gamma"]
        out["theta"] += sign * qty_shares * g["theta"]
        out["vega"] += sign * qty_shares * g["vega"]
        out["rho"] += sign * qty_shares * g["rho"]
        # Notional = qty * spot
        out["notional"] += qty_shares * spot
    return out


def strategy_pnl(legs: list, spot_at_entry: float, spot_now: float, t_years_at_entry: float, t_years_now: float,
                 r: float, sigma: float, premium_paid: float) -> dict:
    """Compute current P&L for a multi-leg position.

    premium_paid: net premium (positive if paid, negative if received)
    Returns: {"mark_value": float, "pnl": float, "delta": float, "gamma": float}
    """
    lot_sizes = {"NIFTY": 75, "BANKNIFTY": 30, "FINNIFTY": 65, "MIDCPNIFTY": 120}
    current_value = 0.0
    greeks_now = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}
    for leg in legs:
        underlying = leg.get("underlying", "NIFTY")
        lot = lot_sizes.get(underlying.upper(), 75)
        qty_shares = leg["qty"] * lot
        sign = 1 if leg["side"].upper() == "BUY" else -1
        # Current value of this leg
        price_now = bs_price(spot_now, leg["strike"], t_years_now, r, sigma, leg["opt_type"]) or 0
        # Entry value of this leg
        price_entry = bs_price(spot_at_entry, leg["strike"], t_years_at_entry, r, sigma, leg["opt_type"]) or 0
        # P&L contribution
        current_value += sign * qty_shares * (price_now - price_entry)
        # Aggregate greeks at current state
        g = greeks(spot_now, leg["strike"], t_years_now, r, sigma, leg["opt_type"])
        if g:
            greeks_now["delta"] += sign * qty_shares * g["delta"]
            greeks_now["gamma"] += sign * qty_shares * g["gamma"]
            greeks_now["theta"] += sign * qty_shares * g["theta"]
            greeks_now["vega"] += sign * qty_shares * g["vega"]
    pnl = current_value - premium_paid
    return {"mark_value": current_value, "pnl": pnl, **greeks_now}


if __name__ == "__main__":
    # Self-test
    spot, strike, t, r, sigma = 24080, 24100, 7/365, 0.065, 0.12
    print(f"CE price @ {spot}: {bs_price(spot, strike, t, r, sigma, 'CE'):.2f}")
    print(f"PE price @ {spot}: {bs_price(spot, strike, t, r, sigma, 'PE'):.2f}")
    g = greeks(spot, strike, t, r, sigma, 'CE')
    print(f"CE greeks: {g}")
    # Iron condor: sell 24500 CE, buy 24700 CE, sell 23700 PE, buy 23500 PE
    legs = [
        {"side": "SELL", "qty": 1, "strike": 24500, "opt_type": "CE", "underlying": "NIFTY"},
        {"side": "BUY", "qty": 1, "strike": 24700, "opt_type": "CE", "underlying": "NIFTY"},
        {"side": "SELL", "qty": 1, "strike": 23700, "opt_type": "PE", "underlying": "NIFTY"},
        {"side": "BUY", "qty": 1, "strike": 23500, "opt_type": "PE", "underlying": "NIFTY"},
    ]
    pg = position_greeks(legs, spot, r, sigma, t)
    print(f"Iron condor greeks: {pg}")
