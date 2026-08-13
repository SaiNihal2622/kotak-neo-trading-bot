"""Risk metrics — drawdown, VaR/CVaR, POP, Kelly, Sharpe/Sortino.

Takes a series of P&L values and produces the standard quant metrics used
by professional risk systems. All functions are pure math — no broker or
network dependencies. This lets us backtest the metrics themselves in
isolation.

Conventions:
  - pnl_series is a list of floats (positive = gain, negative = loss)
    in chronological order. Could be per-trade, per-day, or per-minute.
  - risk_free_rate is annualized (e.g. 0.065 for India 10Y G-Sec ~6.5%)

Usage:
    from kotak_bot.risk.metrics import compute_metrics
    m = compute_metrics(daily_pnl_series, risk_free_rate=0.065, periods_per_year=252)
    print(m.sharpe, m.max_drawdown, m.var_95)
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Iterable, Optional


@dataclass
class RiskMetrics:
    """Bundle of risk metrics for a P&L series."""
    n: int = 0
    total: float = 0.0
    mean: float = 0.0
    std: float = 0.0
    # Drawdown
    max_drawdown: float = 0.0          # largest peak-to-trough drop (Rs, positive number)
    max_drawdown_pct: float = 0.0      # as % of peak equity
    current_drawdown: float = 0.0      # drawdown at the latest point
    # Returns-based (annualized)
    sharpe: float = 0.0                # (mean - rf) / std * sqrt(periods)
    sortino: float = 0.0               # like Sharpe but only downside deviation
    # Risk
    var_95: float = 0.0                # 95% 1-period VaR (Rs, positive = potential loss)
    var_99: float = 0.0                # 99% 1-period VaR
    cvar_95: float = 0.0               # 95% CVaR / expected shortfall (mean of tail)
    cvar_99: float = 0.0               # 99% CVaR
    # Sizing
    kelly_fraction: float = 0.0        # optimal Kelly % (capped at 1.0)
    # Win/loss
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0         # sum(wins) / abs(sum(losses))
    expectancy: float = 0.0           # (win_rate * avg_win) + ((1-win_rate) * avg_loss)
    # POP for the most recent trade (set by analyze_trade)
    pop: float = 0.0                   # probability of profit (0-1)

    def to_dict(self) -> dict:
        return {
            "n": self.n,
            "total": round(self.total, 2),
            "mean": round(self.mean, 4),
            "std": round(self.std, 4),
            "max_drawdown": round(self.max_drawdown, 2),
            "max_drawdown_pct": round(self.max_drawdown_pct * 100, 2),  # as %
            "current_drawdown": round(self.current_drawdown, 2),
            "sharpe": round(self.sharpe, 3),
            "sortino": round(self.sortino, 3),
            "var_95": round(self.var_95, 2),
            "var_99": round(self.var_99, 2),
            "cvar_95": round(self.cvar_95, 2),
            "cvar_99": round(self.cvar_99, 2),
            "kelly_fraction": round(self.kelly_fraction, 4),
            "win_rate": round(self.win_rate * 100, 2),  # as %
            "avg_win": round(self.avg_win, 2),
            "avg_loss": round(self.avg_loss, 2),
            "profit_factor": round(self.profit_factor, 3),
            "expectancy": round(self.expectancy, 2),
            "pop": round(self.pop * 100, 1),  # as %
        }


def _drawdowns(equity_curve: list[float]) -> tuple[list[float], float, float]:
    """Return per-step drawdown (Rs, positive), max DD (Rs), max DD %."""
    if not equity_curve:
        return [], 0.0, 0.0
    peaks: list[float] = []
    peak = equity_curve[0]
    for v in equity_curve:
        if v > peak:
            peak = v
        peaks.append(peak)
    dds = [max(0.0, p - v) for p, v in zip(peaks, equity_curve)]
    max_dd = max(dds) if dds else 0.0
    max_dd_pct = (max_dd / peaks[dds.index(max_dd)]) if max_dd > 0 and peaks[dds.index(max_dd)] > 0 else 0.0
    return dds, max_dd, max_dd_pct


def _var_cvar(returns: list[float], confidence: float) -> tuple[float, float]:
    """Historical VaR and CVaR at given confidence level.

    Returns (var, cvar) — both positive numbers representing potential loss.
    """
    if not returns:
        return 0.0, 0.0
    sorted_r = sorted(returns)
    # Index of the (1-confidence)-quantile (worst case)
    n = len(sorted_r)
    idx = int(math.floor((1.0 - confidence) * n))
    idx = max(0, min(idx, n - 1))
    var = -sorted_r[idx]  # negative of the quantile (positive = loss)
    # CVaR: mean of all returns worse than VaR
    tail = sorted_r[:idx + 1] if idx > 0 else [sorted_r[0]]
    cvar = -statistics.mean(tail) if tail else 0.0
    return max(0.0, var), max(0.0, cvar)


def _downside_dev(returns: list[float], threshold: float = 0.0) -> float:
    """Downside deviation: std of returns below the threshold."""
    downside = [r - threshold for r in returns if r < threshold]
    if not downside:
        return 0.0
    return statistics.stdev(downside) if len(downside) > 1 else abs(downside[0])


def _sharpe(returns: list[float], rf_per_period: float, periods_per_year: int) -> float:
    """Annualized Sharpe ratio."""
    if len(returns) < 2:
        return 0.0
    excess = [r - rf_per_period for r in returns]
    mean = statistics.mean(excess)
    std = statistics.stdev(excess)
    if std <= 0:
        return 0.0
    return (mean / std) * math.sqrt(periods_per_year)


def _sortino(returns: list[float], rf_per_period: float, periods_per_year: int) -> float:
    """Annualized Sortino ratio (only counts downside deviation)."""
    if len(returns) < 2:
        return 0.0
    excess = [r - rf_per_period for r in returns]
    mean = statistics.mean(excess)
    dd = _downside_dev(excess, 0.0)
    if dd <= 0:
        return 0.0
    return (mean / dd) * math.sqrt(periods_per_year)


def _kelly_fraction(win_rate: float, win: float, loss: float) -> float:
    """Kelly fraction: f* = (p*W - (1-p)*L) / (W*L) for binary outcomes.

    Returns 0.0 if invalid inputs.
    Caps at 1.0 (no leverage above 100% of bankroll).
    """
    if win_rate <= 0 or win_rate >= 1 or win <= 0 or loss >= 0:
        return 0.0
    f = (win_rate * win - (1 - win_rate) * (-loss)) / (win * (-loss))
    # Note: loss is stored as negative number. -loss is the absolute risk.
    return max(0.0, min(1.0, f))


def compute_metrics(
    pnl_series: Iterable[float],
    risk_free_rate: float = 0.065,
    periods_per_year: int = 252,
    starting_capital: float = 0.0,
) -> RiskMetrics:
    """Compute all risk metrics for a P&L series.

    Args:
        pnl_series: per-period P&L values (chronological)
        risk_free_rate: annualized
        periods_per_year: 252 for daily, 252*6.25 for hourly, 252*8 for intraday minute
        starting_capital: optional, used for drawdown % calculation
    """
    pnl = list(pnl_series)
    m = RiskMetrics(n=len(pnl))
    if not pnl:
        return m
    # Cumulative equity curve (prepend starting_capital so drawdown is measured
    # from the original capital baseline, not from the first P&L point)
    equity = [starting_capital]
    running = starting_capital
    for p in pnl:
        running += p
        equity.append(running)
    m.total = sum(pnl)
    m.mean = statistics.mean(pnl)
    m.std = statistics.stdev(pnl) if len(pnl) > 1 else 0.0
    # Drawdown (measured on the full equity curve including the starting point)
    dds, m.max_drawdown, m.max_dd_pct = _drawdowns(equity)
    m.max_drawdown_pct = m.max_dd_pct
    m.current_drawdown = dds[-1] if dds else 0.0
    # Per-period risk-free
    rf_per_period = (risk_free_rate / periods_per_year) if periods_per_year > 0 else 0.0
    # Sharpe / Sortino
    m.sharpe = _sharpe(pnl, rf_per_period, periods_per_year)
    m.sortino = _sortino(pnl, rf_per_period, periods_per_year)
    # VaR / CVaR
    m.var_95, m.cvar_95 = _var_cvar(pnl, 0.95)
    m.var_99, m.cvar_99 = _var_cvar(pnl, 0.99)
    # Win/loss
    wins = [x for x in pnl if x > 0]
    losses = [x for x in pnl if x < 0]
    m.win_rate = (len(wins) / len(pnl)) if pnl else 0.0
    m.avg_win = statistics.mean(wins) if wins else 0.0
    m.avg_loss = statistics.mean(losses) if losses else 0.0
    m.profit_factor = (sum(wins) / abs(sum(losses))) if losses and sum(losses) != 0 else 0.0
    m.expectancy = (m.win_rate * m.avg_win) + ((1 - m.win_rate) * m.avg_loss)
    # Kelly (using avg win / avg loss)
    m.kelly_fraction = _kelly_fraction(m.win_rate, m.avg_win, m.avg_loss)
    return m


def probability_of_profit(
    legs: list[dict],
    spot: float,
    target_credit: float,
    max_loss: float,
    vol: Optional[float] = None,
) -> float:
    """Estimate the probability that a multi-leg option position is profitable at expiry.

    For a short iron condor:
      - Win if spot stays between short strikes at expiry
      - POP = P(K1 < S_T < K2) where K1, K2 are the short strikes

    For a long condor / directional:
      - Win if spot moves through the long strike
      - POP = P(S_T > K) for calls, P(S_T < K) for puts

    This uses a simple normal approximation of log(S_T):
      ln(S_T) ~ N(ln(S) + (r - q - 0.5*σ²)T, σ²T)

    Returns probability in [0, 1].
    """
    from kotak_bot.risk.greeks import bs_greeks
    import math
    if not legs:
        return 0.0
    # Find the short strikes (the ones we'd need to NOT cross)
    short_strikes = []
    long_strikes = []
    for leg in legs:
        strike = float(leg.get("strike", 0))
        qty = int(leg.get("qty", 0))
        if qty < 0:  # short
            short_strikes.append(strike)
        else:
            long_strikes.append(strike)
    if not short_strikes:
        return 0.0
    days = float(legs[0].get("days_to_expiry", 7))
    t = max(1e-6, days / 365.0)
    # Use vol from first leg if not provided
    if vol is None:
        vol = float(legs[0].get("iv_override", 0.20) or 0.20)
    vol = max(0.05, min(2.0, vol))
    r, q = 0.065, 0.015
    # Lognormal parameters
    mu = math.log(spot) + (r - q - 0.5 * vol * vol) * t
    sigma = vol * math.sqrt(t)
    # Use normal CDF
    def norm_cdf(x):
        return 0.5 * (1.0 + math.erf((x - mu) / (sigma * math.sqrt(2.0))))
    if len(short_strikes) == 1:
        # Directional: POP = P(S_T > K) for call credit, P(S_T < K) for put credit
        K = short_strikes[0]
        # Find first leg's opt_type
        opt = legs[0].get("opt_type", "CE")
        if opt.upper().startswith("C"):
            return float(norm_cdf(math.log(K)))  # P(S_T < K) for short call
        else:
            return float(1.0 - norm_cdf(math.log(K)))  # P(S_T > K) for short put
    # Iron condor / strangle: P(K1 < S_T < K2)
    sorted_strikes = sorted(short_strikes)
    k_lo, k_hi = sorted_strikes[0], sorted_strikes[-1]
    p_below_hi = norm_cdf(math.log(k_hi))
    p_below_lo = norm_cdf(math.log(k_lo))
    return float(max(0.0, p_below_hi - p_below_lo))
