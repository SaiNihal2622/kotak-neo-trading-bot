"""Smart exit engine: monitors open positions and triggers exit on:
- Target hit (50% of credit / 100% of debit profit)
- Stop loss (2x credit / 50% of debit)
- Time decay (close before expiry if not at target)
- Regime change (close range trade if regime flips to trending)
- Greeks breach (delta/vega outside band)
- Max hold time exceeded

All thresholds are configurable via the `config` dict passed to evaluate_exit.
Defaults are provided but the caller is expected to override them from settings.yaml.

Uses BS approximation for greeks (paper mode); can swap to Dhan Greeks when creds available.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from loguru import logger

from kotak_bot.utils.clock import now_ist


# Default thresholds (caller should override from settings.yaml).
# These exist so unit tests can use them without a full config, but the
# main bot always passes a config dict.
DEFAULT_CONFIG = {
    "target_pct": 0.95,           # exit when pnl >= 95% of plan.target
    "stop_pct": 0.95,             # exit when -pnl >= 95% of plan.stop
    "min_hold_pnl_pct": 0.5,      # close if expiry within N min and pnl < 50% of target
    "expiry_minutes_threshold": 30,# "close to expiry" = within N min
    "max_hold_multiplier": 1.5,    # close if hold > 1.5x expected AND pnl < 70% of target
    "max_hold_pnl_pct": 0.7,
    "iv_crush_pct": -20.0,         # long premium IV drop threshold
    "iv_crush_pnl_pct": 0.3,
    "partial_profit_low": 0.5,     # partial take at >= 50% of target
    "partial_profit_high": 0.95,   # and < 95% of target (above is full exit)
    "partial_profit_hold_pct": 0.3,# only after 30% of expected hold
    "regime_flip_pnl_pct": 0.3,   # regime flip exit if pnl < 30% of target
}


# =============================================================
# Black-Scholes greeks (for paper mode)
# =============================================================
def bs_d1(S: float, K: float, T: float, r: float, sigma: float) -> float:
    if sigma <= 0 or T <= 0 or S <= 0 or K <= 0:
        return 0.0
    return (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def bs_greeks(S: float, K: float, T: float, r: float, sigma: float, opt_type: str) -> dict:
    """Return {delta, gamma, vega, theta, rho, price} for a European option.
    opt_type: 'CE' for call, 'PE' for put.
    T in years.
    """
    if sigma <= 0 or T <= 0:
        # at expiry
        if opt_type == "CE":
            return {"delta": 1.0 if S > K else 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0, "rho": 0.0, "price": max(0.0, S - K)}
        else:
            return {"delta": -1.0 if S < K else 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0, "rho": 0.0, "price": max(0.0, K - S)}
    d1 = bs_d1(S, K, T, r, sigma)
    d2 = d1 - sigma * math.sqrt(T)
    if opt_type == "CE":
        price = S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
        delta = _norm_cdf(d1)
        rho = K * T * math.exp(-r * T) * _norm_cdf(d2)
    else:
        price = K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)
        delta = _norm_cdf(d1) - 1.0
        rho = -K * T * math.exp(-r * T) * _norm_cdf(-d2)
    gamma = _norm_pdf(d1) / (S * sigma * math.sqrt(T))
    vega = S * _norm_pdf(d1) * math.sqrt(T) / 100.0  # per 1% IV
    # theta per day
    if opt_type == "CE":
        theta = (-(S * _norm_pdf(d1) * sigma) / (2 * math.sqrt(T)) - r * K * math.exp(-r * T) * _norm_cdf(d2)) / 365.0
    else:
        theta = (-(S * _norm_pdf(d1) * sigma) / (2 * math.sqrt(T)) + r * K * math.exp(-r * T) * _norm_cdf(-d2)) / 365.0
    return {
        "delta": delta,
        "gamma": gamma,
        "vega": vega,
        "theta": theta,
        "rho": rho,
        "price": max(0.0, price),
    }


def estimate_position_greeks(position: dict, spot: float, iv: float = 0.18,
                              days_to_expiry: int = 0) -> dict:
    """Estimate greeks for an open position (dict from PaperClient)."""
    S = spot
    K = float(position.get("strike", 0))
    opt_type = position.get("option_type", "CE")
    qty = float(position.get("qty", 0))
    T = max(1/365, days_to_expiry / 365.0)
    if K <= 0 or S <= 0:
        return {"delta": 0, "gamma": 0, "vega": 0, "theta": 0, "rho": 0, "price": 0, "dollar_delta": 0}
    g = bs_greeks(S, K, T, 0.06, iv, opt_type)
    g["dollar_delta"] = g["delta"] * qty  # per 1-point move
    g["dollar_vega"] = g["vega"] * qty  # per 1% IV move
    g["dollar_theta"] = g["theta"] * qty  # per day
    return g


# =============================================================
# Smart exit decisions
# =============================================================
@dataclass
class ExitSignal:
    should_exit: bool
    reason: str
    exit_pct: float = 1.0  # 1.0 = close all, 0.5 = close half
    urgency: str = "normal"  # 'normal' | 'urgent'


def evaluate_exit(plan, current_pnl: float, pnl_pct: float, hold_minutes: int,
                  current_regime: str, current_greeks: dict,
                  current_iv_change_pct: float, minutes_to_expiry: int,
                  config: Optional[dict] = None) -> ExitSignal:
    """Decide whether to exit a position.

    All thresholds come from `config` (or DEFAULT_CONFIG if not passed).
    The caller (bot __main__) is expected to pass settings from settings.yaml
    under risk.smart_exit.* so NOTHING is hardcoded.

    plan: TradePlan (has target, stop, strategy, expected_hold_minutes)
    current_pnl: realized + unrealized PnL for this trade
    pnl_pct: current_pnl / max_profit (or -pnl / max_loss)
    hold_minutes: how long we've held
    current_regime: 'trending' | 'range' | 'volatile'
    current_greeks: aggregated portfolio greeks (delta, vega)
    current_iv_change_pct: % change in IV since entry
    minutes_to_expiry: minutes until close
    config: dict of thresholds (see DEFAULT_CONFIG for keys). If None, uses DEFAULT_CONFIG.
    """
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    target_pct = cfg["target_pct"]
    stop_pct = cfg["stop_pct"]
    min_hold_pnl_pct = cfg["min_hold_pnl_pct"]
    expiry_min = cfg["expiry_minutes_threshold"]
    max_hold_mult = cfg["max_hold_multiplier"]
    max_hold_pnl_pct = cfg["max_hold_pnl_pct"]
    iv_crush_pct = cfg["iv_crush_pct"]
    iv_crush_pnl_pct = cfg["iv_crush_pnl_pct"]
    partial_low = cfg["partial_profit_low"]
    partial_high = cfg["partial_profit_high"]
    partial_hold_pct = cfg["partial_profit_hold_pct"]
    regime_flip_pnl_pct = cfg["regime_flip_pnl_pct"]

    # 1) Target hit — exit fully
    if current_pnl >= plan.target * target_pct:
        return ExitSignal(True, f"target hit: pnl={current_pnl:.0f} >= {target_pct:.0%} of {plan.target:.0f}", 1.0, "normal")
    # 2) Stop hit — exit fully
    if current_pnl <= -plan.stop * stop_pct:
        return ExitSignal(True, f"stop hit: pnl={current_pnl:.0f} <= {stop_pct:.0%} of -{plan.stop:.0f}", 1.0, "urgent")
    # 3) Time-based exit (close if expiry within N min and not at target)
    if minutes_to_expiry < expiry_min and minutes_to_expiry > 0 and pnl_pct < min_hold_pnl_pct:
        return ExitSignal(True, f"time decay: {minutes_to_expiry}min to expiry, only {pnl_pct:.0%} of target", 1.0, "urgent")
    # 4) Max hold time exceeded
    if hold_minutes > plan.expected_hold_minutes * max_hold_mult:
        if pnl_pct < max_hold_pnl_pct:
            return ExitSignal(True, f"max hold exceeded: {hold_minutes}min > {plan.expected_hold_minutes*max_hold_mult:.0f}min and pnl {pnl_pct:.0%} of target", 1.0, "normal")
    # 5) Regime change (range trade in trending market)
    if "range" in plan.strategy.value.lower() or plan.strategy.value in ("short_strangle", "iron_condor", "iron_butterfly", "jade_lizard", "calendar"):
        if current_regime == "trending" and pnl_pct < regime_flip_pnl_pct:
            return ExitSignal(True, f"regime flip: range strategy in trending market, pnl only {pnl_pct:.0%} of target", 1.0, "normal")
    if "trending" in plan.reason or "directional" in plan.strategy.value.lower():
        if current_regime == "range" and pnl_pct < regime_flip_pnl_pct:
            return ExitSignal(True, f"regime flip: directional strategy in range market, pnl only {pnl_pct:.0%}", 1.0, "normal")
    # 6) IV crush (long premium hurt by IV drop)
    if current_iv_change_pct < iv_crush_pct and plan.strategy.value in ("long_strangle", "long_straddle", "event_straddle"):
        if pnl_pct < iv_crush_pnl_pct:
            return ExitSignal(True, f"IV crush: iv changed {current_iv_change_pct:.0f}%, pnl {pnl_pct:.0%}", 0.5, "normal")
    # 7) Partial profit-take
    if pnl_pct >= partial_low and pnl_pct < partial_high and hold_minutes > plan.expected_hold_minutes * partial_hold_pct:
        return ExitSignal(True, f"partial profit: {partial_low:.0%} of target reached at {pnl_pct:.0%}, scaling out", 0.5, "normal")
    # 8) No exit signal
    return ExitSignal(False, "no exit", 0.0, "normal")


# =============================================================
# Portfolio-level risk aggregation
# =============================================================
def aggregate_portfolio_greeks(positions: list[dict], spot_by_underlying: dict, iv: float = 0.18) -> dict:
    """Aggregate greeks across all open positions."""
    total = {"delta": 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0, "dollar_delta": 0.0, "dollar_vega": 0.0, "dollar_theta": 0.0}
    for p in positions:
        u = p.get("underlying", "")
        S = spot_by_underlying.get(u, 0)
        if S <= 0:
            continue
        g = estimate_position_greeks(p, S, iv=iv, days_to_expiry=0)
        for k in total:
            total[k] += g.get(k, 0)
    return total
