"""Quant alpha layer — the LLM's quantitative toolkit.

Pure Python (no numpy/scipy). Designed to be called from quant_service.py
and from the LLM context. Outputs a JSON snapshot at
data_cache/quant_alpha.json (refreshed every 5 min during market hours).

Components:
  1. VOL FORECASTING — EWMA + GARCH(1,1) one-step-ahead variance.
     The LLM uses this for strike selection, position sizing, and to know
     whether to deploy lottery tickets (low forecast vol = coiled spring).
  2. KELLY SIZING — Kelly fraction from historical win rate + payoff ratio.
     Vol-targeted sizing alternative when win rate is unknown.
  3. IV SURFACE — ATM IV, 25-delta skew, term-structure slope per underlying.
     The LLM uses this to pick strikes (sell high IV, buy low IV) and to
     detect mispriced options.
  4. EXECUTION QUALITY — slippage tracker (fill vs expected), fill rate,
     avg slippage by side (BUY/SELL). The LLM uses this to calibrate price
     limits and to know which order types to use.
  5. PORTFOLIO RISK — Historical-simulation VaR (95%, 1-day), max drawdown,
     correlation matrix of open underlyings, beta vs NIFTY, sector exposure.
     The LLM uses this to enforce risk caps and to know when to de-risk.
  6. REGIME DETECTION — bull/bear/sideways classification from EMA alignment
     + vol regime (low/normal/high) from realized vol vs forecast.

Self-evolution: this module's outputs feed the LLM prompt. The LLM uses
the metrics to make better decisions; the system records outcomes in
performance_tracker.py; the nightly self-review (23:00) reviews the
metrics to suggest prompt refinements.
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
DATA = ROOT / 'data_cache'
PERF = DATA / 'performance'
PERF.mkdir(parents=True, exist_ok=True)
ALPHA_PATH = DATA / 'quant_alpha.json'

# Symbols covered
INDICES = ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY']
SECTORS = {
    'BANK': ['HDFCBANK', 'ICICIBANK', 'SBIN', 'AXISBANK', 'KOTAKBANK', 'INDUSINDBK', 'BAJFINANCE'],
    'IT': ['TCS', 'INFY', 'HCLTECH'],
    'AUTO': ['MARUTI', 'M&M', 'TATAMOTORS', 'BAJFINANCE'],
    'PHARMA': ['SUNPHARMA'],
    'FMCG': ['ITC', 'HINDUNILVR'],
    'ENERGY': ['RELIANCE', 'POWERGRID', 'NTPC'],
    'METALS': ['TATASTEEL'],
    'CONSUMER': ['ASIANPAINT', 'TITAN', 'BHARTIARTL'],
    'INDUSTRIAL': ['LT'],
}


# ============================================================================
# 1. VOL FORECASTING — EWMA + GARCH(1,1)
# ============================================================================

def returns_from_closes(closes: list[float]) -> list[float]:
    """Simple log returns from a close series."""
    if len(closes) < 2:
        return []
    return [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i - 1] > 0]


def forecast_vol_ewma(returns: list[float], halflife: int = 20) -> Optional[dict]:
    """Exponentially-weighted moving average volatility forecast.
    Returns {next_vol_annualized, current_vol_annualized, vol_regime}."""
    if len(returns) < 5:
        return None
    alpha = 1 - math.exp(-math.log(2) / halflife)
    var_ewma = returns[0] ** 2
    for r in returns[1:]:
        var_ewma = alpha * (r ** 2) + (1 - alpha) * var_ewma
    # Annualize: per-minute returns -> per-year (252 * 375 mins for NSE)
    # For daily returns: multiply by 252
    # Assume the input is daily returns
    current_vol_d = math.sqrt(var_ewma)
    current_vol_ann = current_vol_d * math.sqrt(252)
    # Forecast = EWMA of squared returns, one-step-ahead
    forecast_var = alpha * (returns[-1] ** 2) + (1 - alpha) * var_ewma
    forecast_vol_ann = math.sqrt(forecast_var) * math.sqrt(252)
    regime = 'low' if current_vol_ann < 0.12 else 'normal' if current_vol_ann < 0.20 else 'high'
    return {
        'current_vol_ann': round(current_vol_ann, 4),
        'forecast_vol_ann': round(forecast_vol_ann, 4),
        'vol_regime': regime,
        'halflife_days': halflife,
    }


def forecast_vol_garch(returns: list[float], omega: float = 0.000001, alpha: float = 0.08, beta: float = 0.90) -> Optional[dict]:
    """GARCH(1,1) one-step-ahead variance forecast.
    sigma2_t = omega + alpha * r_{t-1}^2 + beta * sigma2_{t-1}
    Long-run variance = omega / (1 - alpha - beta)
    Default parameters work for daily returns; for intraday, scale omega."""
    if len(returns) < 10:
        return None
    # Initialize with unconditional variance
    var_uncond = sum(r ** 2 for r in returns) / len(returns)
    var_t = var_uncond
    var_series = [var_t]
    for r in returns[1:]:
        var_t = omega + alpha * (r ** 2) + beta * var_t
        var_series.append(var_t)
    # One-step-ahead forecast
    forecast_var = omega + alpha * (returns[-1] ** 2) + beta * var_t
    current_vol_d = math.sqrt(var_t)
    forecast_vol_d = math.sqrt(forecast_var)
    # Annualize (daily)
    current_vol_ann = current_vol_d * math.sqrt(252)
    forecast_vol_ann = forecast_vol_d * math.sqrt(252)
    # Persistence
    persistence = alpha + beta
    half_life = math.log(0.5) / math.log(persistence) if 0 < persistence < 1 else None
    regime = 'low' if current_vol_ann < 0.12 else 'normal' if current_vol_ann < 0.20 else 'high'
    return {
        'current_vol_ann': round(current_vol_ann, 4),
        'forecast_vol_ann': round(forecast_vol_ann, 4),
        'vol_regime': regime,
        'persistence': round(persistence, 4),
        'half_life_days': round(half_life, 1) if half_life else None,
        'omega': omega, 'alpha': alpha, 'beta': beta,
    }


# ============================================================================
# 2. KELLY SIZING + VOL-TARGETED SIZING
# ============================================================================

def kelly_fraction(win_rate: float, avg_win: float, avg_loss: float) -> dict:
    """Kelly fraction for binary outcomes: f* = (p/a - q)/b
    where p = win rate, q = 1-p, a = avg_win / avg_loss, b = 1
    Conservative Kelly = f* / 2 (Half-Kelly is widely used to avoid ruin).
    Returns {full_kelly, half_kelly, expected_growth, recommendation}."""
    if win_rate <= 0 or win_rate >= 1 or avg_win <= 0 or avg_loss <= 0:
        return {'full_kelly': 0.0, 'half_kelly': 0.0, 'expected_growth': 0.0, 'recommendation': 'no_edge'}
    b = avg_win / avg_loss
    full_kelly = win_rate - (1 - win_rate) / b
    half_kelly = full_kelly / 2
    # Expected log growth at Kelly
    if full_kelly > 0:
        ev_log = win_rate * math.log(1 + full_kelly * b) + (1 - win_rate) * math.log(1 - full_kelly)
    else:
        ev_log = 0
    rec = 'aggressive' if full_kelly > 0.3 else 'normal' if full_kelly > 0.1 else 'conservative' if full_kelly > 0 else 'no_edge'
    return {
        'full_kelly': round(full_kelly, 4),
        'half_kelly': round(half_kelly, 4),
        'expected_log_growth': round(ev_log, 5),
        'recommendation': rec,
    }


def vol_targeted_size(capital: float, target_vol_ann: float, forecast_vol_ann: float, max_risk_pct: float = 0.05) -> dict:
    """Vol-targeted position size: scale position to hit target annualized vol.
    size_pct = min(target_vol / forecast_vol, max_risk_pct)
    If forecast vol is HIGH, position is SMALLER. If LOW, larger.
    Capped at max_risk_pct (5% default)."""
    if forecast_vol_ann <= 0 or target_vol_ann <= 0:
        return {'size_pct': 0.0, 'size_rupees': 0.0, 'reason': 'invalid_vol'}
    raw_size = target_vol_ann / forecast_vol_ann
    capped = min(raw_size, max_risk_pct)
    return {
        'size_pct': round(capped, 4),
        'size_rupees': round(capital * capped, 2),
        'raw_size_pct': round(raw_size, 4),
        'capped': raw_size > max_risk_pct,
    }


# ============================================================================
# 3. IV SURFACE — ATM IV, skew, term structure
# ============================================================================

def compute_iv_metrics(chain: dict, spot: float) -> dict:
    """Extract IV metrics from an option chain dict (from option_chains.json).
    chain format: {'chains': {'NIFTY': {'spot': X, 'expiries': [{'date':..., 'strikes': [{'strike':, 'ce_iv':, 'pe_iv':, 'ce_oi':, 'pe_oi':}]}]}}
    Or the legacy format: {'spot': X, 'strikes': [{'strike', 'ce_ltp', 'pe_ltp', 'ce_iv', 'pe_iv', 'ce_oi', 'pe_oi'}]}"""
    if not chain or not spot or spot <= 0:
        return {}
    # Find nearest ATM strike
    strikes = chain.get('strikes') or []
    if not strikes:
        # Try nested format
        expiries = chain.get('expiries') or []
        if expiries:
            strikes = expiries[0].get('strikes', [])
    if not strikes:
        return {}
    atm_idx = min(range(len(strikes)), key=lambda i: abs(strikes[i].get('strike', 0) - spot))
    atm = strikes[atm_idx]
    atm_iv = ((atm.get('ce_iv') or 0) + (atm.get('pe_iv') or 0)) / 2
    # 25-delta skew: OTM put IV - OTM call IV (proxy: 5% OTM each side)
    otm_pct = 0.05
    otm_strike_target = spot * (1 - otm_pct)
    otm_call_target = spot * (1 + otm_pct)
    otm_put = min(strikes, key=lambda s: abs(s.get('strike', 0) - otm_strike_target))
    otm_call = min(strikes, key=lambda s: abs(s.get('strike', 0) - otm_call_target))
    put_iv = otm_put.get('pe_iv') or 0
    call_iv = otm_call.get('ce_iv') or 0
    skew_25d = put_iv - call_iv  # positive = bearish fear premium
    # PCR (put-call ratio by OI)
    total_ce_oi = sum(s.get('ce_oi', 0) or 0 for s in strikes)
    total_pe_oi = sum(s.get('pe_oi', 0) or 0 for s in strikes)
    pcr = total_pe_oi / total_ce_oi if total_ce_oi > 0 else 1.0
    return {
        'spot': spot,
        'atm_strike': atm.get('strike'),
        'atm_iv': round(atm_iv, 2) if atm_iv else None,
        'skew_25d': round(skew_25d, 2) if put_iv and call_iv else None,
        'pcr_oi': round(pcr, 3),
        'total_ce_oi': total_ce_oi,
        'total_pe_oi': total_pe_oi,
    }


# ============================================================================
# 4. EXECUTION QUALITY
# ============================================================================

class ExecutionTracker:
    """Tracks fill prices vs expected. Used by the LLM to calibrate."""
    def __init__(self, path: Path = None):
        self.path = path or (PERF / 'execution_quality.jsonl')
        self.fills: deque = deque(maxlen=200)  # in-memory recent fills
        if self.path.exists():
            try:
                for line in self.path.read_text(encoding='utf-8', errors='ignore').splitlines()[-200:]:
                    try:
                        self.fills.append(json.loads(line))
                    except Exception:
                        continue
            except Exception:
                pass

    def record_fill(self, order_id: str, symbol: str, side: str, qty: int,
                    expected_price: float, fill_price: float, ts: Optional[str] = None) -> None:
        slippage = (fill_price - expected_price) if side.upper() == 'BUY' else (expected_price - fill_price)
        slippage_pct = (slippage / expected_price * 100) if expected_price else 0
        rec = {
            'ts': ts or datetime.now().isoformat(timespec='seconds'),
            'order_id': order_id, 'symbol': symbol, 'side': side.upper(),
            'qty': qty, 'expected': expected_price, 'fill': fill_price,
            'slippage': round(slippage, 4), 'slippage_pct': round(slippage_pct, 4),
        }
        self.fills.append(rec)
        try:
            with self.path.open('a', encoding='utf-8') as f:
                f.write(json.dumps(rec) + "\n")
        except Exception:
            pass

    def get_stats(self, last_n: int = 20) -> dict:
        if not self.fills:
            return {'n_fills': 0}
        recent = list(self.fills)[-last_n:]
        slippages = [f['slippage_pct'] for f in recent if f.get('slippage_pct') is not None]
        if not slippages:
            return {'n_fills': len(recent)}
        return {
            'n_fills': len(recent),
            'avg_slippage_pct': round(sum(slippages) / len(slippages), 4),
            'max_slippage_pct': round(max(slippages), 4),
            'min_slippage_pct': round(min(slippages), 4),
            'positive_slippage_count': sum(1 for s in slippages if s > 0),  # bad for us
            'negative_slippage_count': sum(1 for s in slippages if s < 0),  # good for us
        }


# ============================================================================
# 5. PORTFOLIO RISK
# ============================================================================

def compute_var(returns: list[float], confidence: float = 0.95) -> Optional[dict]:
    """Historical-simulation Value at Risk. returns: daily returns list.
    Returns {var_pct, var_rupees_on_1L, cvar_pct}."""
    if len(returns) < 20:
        return None
    sorted_rets = sorted(returns)
    idx = int((1 - confidence) * len(sorted_rets))
    var_pct = -sorted_rets[idx]  # VaR is positive (a loss)
    # CVaR: average of returns below VaR
    tail = sorted_rets[:idx + 1]
    cvar_pct = -sum(tail) / len(tail) if tail else var_pct
    return {
        'var_pct': round(var_pct, 4),
        'var_rupees_on_1L': round(var_pct * 100000, 2),
        'cvar_pct': round(cvar_pct, 4),
        'confidence': confidence,
        'n_obs': len(returns),
    }


def compute_max_drawdown(pnl_series: list[float]) -> dict:
    """Max drawdown from a cumulative P&L series (already cumulative).
    Returns {max_dd, max_dd_pct, peak_idx, trough_idx}."""
    if len(pnl_series) < 2:
        return {'max_dd': 0, 'max_dd_pct': 0}
    peak = pnl_series[0]
    peak_idx = 0
    max_dd = 0
    max_dd_idx = 0
    for i, p in enumerate(pnl_series):
        if p > peak:
            peak = p
            peak_idx = i
        dd = peak - p
        if dd > max_dd:
            max_dd = dd
            max_dd_idx = i
    max_dd_pct = (max_dd / peak * 100) if peak > 0 else 0
    return {
        'max_dd': round(max_dd, 2),
        'max_dd_pct': round(max_dd_pct, 2),
        'peak_idx': peak_idx,
        'trough_idx': max_dd_idx,
    }


def compute_correlation_matrix(returns_dict: dict[str, list[float]]) -> dict:
    """Compute pairwise correlation matrix from a dict of return series.
    Returns {symbols: [...], matrix: [[...]]}."""
    syms = list(returns_dict.keys())
    n = len(syms)
    if n < 2:
        return {'symbols': syms, 'matrix': [[1.0]] if n == 1 else []}
    matrix = [[0.0] * n for _ in range(n)]
    for i in range(n):
        matrix[i][i] = 1.0
    for i in range(n):
        for j in range(i + 1, n):
            ri, rj = returns_dict[syms[i]], returns_dict[syms[j]]
            m = min(len(ri), len(rj))
            if m < 5:
                corr = 0
            else:
                ri_t = ri[-m:]
                rj_t = rj[-m:]
                mean_i = sum(ri_t) / m
                mean_j = sum(rj_t) / m
                num = sum((ri_t[k] - mean_i) * (rj_t[k] - mean_j) for k in range(m))
                den_i = math.sqrt(sum((ri_t[k] - mean_i) ** 2 for k in range(m)))
                den_j = math.sqrt(sum((rj_t[k] - mean_j) ** 2 for k in range(m)))
                corr = num / (den_i * den_j) if (den_i * den_j) > 0 else 0
            matrix[i][j] = corr
            matrix[j][i] = corr
    return {
        'symbols': syms,
        'matrix': [[round(v, 3) for v in row] for row in matrix],
    }


def compute_sector_exposure(positions: dict) -> dict:
    """Compute sector exposure from open positions.
    positions: {symbol: {qty, underlying, ...}}"""
    exposure: dict[str, float] = {}
    for sym, pos in positions.items():
        if not isinstance(pos, dict):
            continue
        underlying = (pos.get('underlying') or sym).upper()
        qty = float(pos.get('qty', 0) or 0)
        sign = 1 if pos.get('side', 'BUY').upper() == 'BUY' else -1
        notional = qty * sign  # proxy: count, not rupees
        for sector, members in SECTORS.items():
            if underlying in members:
                exposure[sector] = exposure.get(sector, 0) + notional
                break
        else:
            exposure['OTHER'] = exposure.get('OTHER', 0) + notional
    return exposure


# ============================================================================
# 6. REGIME DETECTION
# ============================================================================

def detect_regime(closes: list[float], vix: float = 0) -> dict:
    """Detect market regime: trend (up/down/sideways) + vol regime (low/normal/high).
    Uses EMA alignment + realized vol + VIX."""
    if len(closes) < 30:
        return {'trend': 'unknown', 'vol_regime': 'unknown'}
    ema9 = CandleEngine._ema(closes, 9) if hasattr(CandleEngine, '_ema') else None
    ema21 = CandleEngine._ema(closes, 21) if hasattr(CandleEngine, '_ema') else None
    ema50 = CandleEngine._ema(closes, 50) if hasattr(CandleEngine, '_ema') else None
    if not (ema9 and ema21 and ema50):
        # Fallback: simple slope
        slope = (closes[-1] - closes[-20]) / closes[-20] if closes[-20] > 0 else 0
        trend = 'up' if slope > 0.01 else 'down' if slope < -0.01 else 'sideways'
    else:
        if ema9 > ema21 > ema50:
            trend = 'up'
        elif ema9 < ema21 < ema50:
            trend = 'down'
        else:
            trend = 'sideways'
    # Vol regime from VIX if available, else from realized vol
    if vix > 0:
        vol_regime = 'low' if vix < 12 else 'normal' if vix < 16 else 'high'
    else:
        rets = returns_from_closes(closes[-30:])
        if rets:
            rvol = math.sqrt(sum(r ** 2 for r in rets) / len(rets)) * math.sqrt(252)
            vol_regime = 'low' if rvol < 0.12 else 'normal' if rvol < 0.20 else 'high'
        else:
            vol_regime = 'unknown'
    return {'trend': trend, 'vol_regime': vol_regime}


# Avoid circular import with candle_engine; just import the EMA function
sys.path.insert(0, str(ROOT / 'scripts'))
try:
    from candle_engine import CandleEngine
except Exception:
    CandleEngine = None


# ============================================================================
# AGGREGATE — build the alpha snapshot for the LLM
# ============================================================================

def build_alpha_snapshot() -> dict:
    """Read all data sources and build a comprehensive alpha snapshot.
    Called every 5 min during market hours. Writes to data_cache/quant_alpha.json."""
    snap = {
        'ts': datetime.now().isoformat(timespec='seconds'),
        'vol_forecasts': {},
        'iv_metrics': {},
        'regime_per_symbol': {},
        'execution_quality': {},
        'portfolio_risk': {},
        'kelly': {},
    }
    # Load candle data
    candle_agg_path = DATA / 'candles_aggregate.json'
    candles = {}
    if candle_agg_path.exists():
        try:
            candles = json.loads(candle_agg_path.read_text(encoding='utf-8')).get('symbols', {})
        except Exception:
            pass
    # Vol forecast + regime per symbol
    for sym, c in candles.items():
        closes = [b.get('c') for b in [c.get('latest_bars', {}).get(tf, {}) for tf in ['5m', '15m', '1m']] if b and b.get('c')]
        if not closes and c.get('ltp'):
            closes = [c['ltp']]
        if not closes:
            continue
        # Use 1m closes for vol forecast
        bars_1m = candles.get(sym, {}).get('n_bars_1m', 0)
        if bars_1m >= 30:
            rets = returns_from_closes(closes)
            ewma = forecast_vol_ewma(rets, halflife=20)
            garch = forecast_vol_garch(rets)
            snap['vol_forecasts'][sym] = {'ewma': ewma, 'garch': garch}
        # Regime
        ltp = c.get('ltp', 0)
        vix = c.get('vwap') or 0  # proxy if no VIX
        snap['regime_per_symbol'][sym] = detect_regime(closes, vix=0)
    # IV metrics from option chains
    chains_path = DATA / 'option_chains.json'
    if chains_path.exists():
        try:
            chains = json.loads(chains_path.read_text(encoding='utf-8'))
            for sym in ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY']:
                chain = chains.get('chains', {}).get(sym, {})
                spot = chain.get('spot') or candles.get(sym, {}).get('ltp', 0)
                if chain and spot:
                    snap['iv_metrics'][sym] = compute_iv_metrics(chain, spot)
        except Exception:
            pass
    # Execution quality
    tracker = ExecutionTracker()
    snap['execution_quality'] = tracker.get_stats(last_n=20)
    # Portfolio risk
    try:
        sys.path.insert(0, str(ROOT / 'scripts'))
        from performance_tracker import DECISIONS_PATH
        decisions = []
        if DECISIONS_PATH.exists():
            for line in DECISIONS_PATH.read_text(encoding='utf-8', errors='ignore').splitlines()[-50:]:
                try:
                    decisions.append(json.loads(line))
                except Exception:
                    continue
        # Closed decisions: compute cumulative P&L
        closed = [d for d in decisions if d.get('status') == 'closed']
        if closed:
            cumulative_pnl = []
            running = 0
            for d in closed:
                running += d.get('pnl', 0) or 0
                cumulative_pnl.append(running)
            dd = compute_max_drawdown(cumulative_pnl)
            snap['portfolio_risk']['max_drawdown'] = dd
            # Per-day P&L series for VaR
            daily_pnl = {}
            for d in closed:
                ts = (d.get('close_ts') or d.get('ts') or '')[:10]
                if ts:
                    daily_pnl[ts] = daily_pnl.get(ts, 0) + (d.get('pnl', 0) or 0)
            daily_rets = [v / 100000 for v in daily_pnl.values()]  # % of capital
            if len(daily_rets) >= 5:
                var = compute_var(daily_rets, 0.95)
                if var:
                    snap['portfolio_risk']['var_95_1d'] = var
        # Kelly from performance
        from performance_tracker import get_strategy_performance
        strategies = get_strategy_performance()
        for strat_name, perf in strategies.items():
            if perf.get('count', 0) >= 5:
                wins = perf.get('wins', 0)
                losses = perf.get('losses', 0)
                avg_win = perf.get('avg_win', 0) or 0
                avg_loss = abs(perf.get('avg_loss', 0) or 0)
                total = wins + losses
                if total > 0:
                    win_rate = wins / total
                    snap['kelly'][strat_name] = kelly_fraction(win_rate, avg_win, avg_loss)
    except Exception as e:
        snap['portfolio_risk']['error'] = str(e)
    # Sector exposure
    try:
        paper_path = DATA / 'paper_state.json'
        if paper_path.exists():
            paper = json.loads(paper_path.read_text(encoding='utf-8'))
            positions = paper.get('positions', {}) or {}
            snap['portfolio_risk']['sector_exposure'] = compute_sector_exposure(positions)
    except Exception:
        pass
    # Write
    try:
        ALPHA_PATH.write_text(json.dumps(snap, indent=2, default=str), encoding='utf-8')
    except Exception:
        pass
    return snap


def get_alpha_context_for_llm() -> dict:
    """Build a compact alpha context for the LLM. Top-level signals only."""
    if not ALPHA_PATH.exists():
        return {}
    try:
        snap = json.loads(ALPHA_PATH.read_text(encoding='utf-8'))
    except Exception:
        return {}
    out = {'ts': snap.get('ts')}
    # Vol forecasts (top 5 by forecast vol)
    vf = snap.get('vol_forecasts', {})
    vol_summary = []
    for sym, v in vf.items():
        g = v.get('garch') or v.get('ewma') or {}
        vol_summary.append({
            'sym': sym, 'vol_ann': g.get('current_vol_ann'),
            'forecast_vol_ann': g.get('forecast_vol_ann'),
            'regime': g.get('vol_regime'),
        })
    vol_summary.sort(key=lambda x: -(x.get('vol_ann') or 0))
    out['vol_forecasts'] = vol_summary[:8]
    # IV metrics for the 4 indices
    out['iv_metrics'] = snap.get('iv_metrics', {})
    # Regime
    out['regime'] = snap.get('regime_per_symbol', {})
    # Execution quality
    out['execution_quality'] = snap.get('execution_quality', {})
    # Portfolio risk
    pr = snap.get('portfolio_risk', {})
    out['portfolio_risk'] = {
        'var_95_1d_pct': pr.get('var_95_1d', {}).get('var_pct'),
        'max_dd': pr.get('max_drawdown', {}).get('max_dd'),
        'sector_exposure': pr.get('sector_exposure', {}),
    }
    # Kelly
    out['kelly'] = snap.get('kelly', {})
    return out


if __name__ == '__main__':
    snap = build_alpha_snapshot()
    print(f"alpha snapshot: {len(snap.get('vol_forecasts', {}))} vol forecasts, "
          f"{len(snap.get('iv_metrics', {}))} IV metrics, "
          f"{len(snap.get('kelly', {}))} kelly calcs")
    ctx = get_alpha_context_for_llm()
    print(json.dumps(ctx, indent=2, default=str)[:2000])
