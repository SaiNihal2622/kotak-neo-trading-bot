"""Strategy selector — picks the BEST strategy for current state from data.

PHASE 8 (2026-10-01): the brain is no longer template-driven. Strategy
selection itself is now data-driven.

The old code:
    if regime == "trending_up" and adx > 0.25 and rsi > 60:
        return nifty_cash_long  # ALWAYS this, no matter what
    if regime == "trending_down" and adx > 0.25 and rsi < 40:
        return nifty_cash_short  # ALWAYS this

The new code:
    1. Compute a CANDIDATE SET of strategies based on regime:
       - trending_up/mild_up   → nifty_cash_long, nifty_swing_long, nifty_long_call
       - trending_down/mild_down → nifty_cash_short, nifty_swing_short, nifty_long_put
       - range_bound           → nifty_iron_condor, nifty_short_straddle
    2. For each candidate, score = (win_rate * avg_gain) - ((1-win_rate) * avg_loss)
    3. Pull stats from:
       a. (regime, strategy) lookup in online_learner (primary)
       b. strategy overall stats (fallback when n < 3)
       c. Bayesian EV from signal_history (cold-start when n = 0)
    4. Pick the highest-scoring strategy with positive EV.
    5. If all negative → HOLD.

This is REAL intelligence: the system looks at its own track record
in the current regime and picks what has worked. Over time, strategies
that lose money in regime X get deprioritized; strategies that win get
favored.

DESIGN:
- Stateless function: takes state, returns ranked candidates + recommendation.
- Caches results in data_cache/strategy_selector_state.json (atomic).
- Cold-start behavior: when no data, use Bayesian EV from signal_history.

WATCH FOR:
- Strategies with n < 3 are unreliable (high variance). We require
  n >= MIN_N_FOR_DATA = 3 before trusting local stats.
- Bayesian EV (yfinance) is the floor: even with zero local data, we
  still rank by what the math says about the strategy class.
- Regime mismatches: e.g., nifty_long_call in trending_down doesn't
  make sense — exclude from candidates.
"""
from __future__ import annotations

import json
import math
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data_cache"
SELECTOR_STATE = DATA_DIR / "strategy_selector_state.json"

IST = timezone(timedelta(hours=5, minutes=30))

# Minimum local samples before trusting per-(regime, strategy) stats
MIN_N_FOR_DATA = 3
# Minimum total local samples to use local-only stats
MIN_N_TOTAL_FOR_DATA = 5
# Smoothing weight for combining local stats with Bayesian prior
LOCAL_PRIOR_WEIGHT = 50

# Assumed notional for converting local journal P&L (in rupees) to
# percent of position size. Same as bayesian_decision.ASSUMED_NOTIONAL.
ASSUMED_NOTIONAL_PCT_CONV = 100_000.0


# Candidate strategies per regime. Tuple format:
# (strategy_name, side, segment, description)
CANDIDATES_BY_REGIME = {
    "trending_up": [
        ("nifty_cash_long", "BUY", "nse_cm", "Cash NIFTY long"),
        ("nifty_swing_long", "BUY", "nse_cm", "Multi-day swing long"),
        ("nifty_long_call", "BUY", "nfo", "Bullish call option"),
    ],
    "mild_up": [
        ("nifty_cash_long", "BUY", "nse_cm", "Cash NIFTY long (mild)"),
        ("nifty_long_call", "BUY", "nfo", "Bullish call option (mild)"),
    ],
    "trending_down": [
        ("nifty_cash_short", "SELL", "nse_cm", "Cash NIFTY short"),
        ("nifty_swing_short", "SELL", "nse_cm", "Multi-day swing short"),
        ("nifty_long_put", "BUY", "nfo", "Bearish put option"),
    ],
    "mild_down": [
        ("nifty_cash_short", "SELL", "nse_cm", "Cash NIFTY short (mild)"),
        ("nifty_long_put", "BUY", "nfo", "Bearish put option (mild)"),
    ],
    "range_bound": [
        ("nifty_iron_condor", "SELL", "nfo", "Range-bound vol seller"),
        ("nifty_short_straddle", "SELL", "nfo", "Vol seller (no wings)"),
    ],
    "unknown": [
        ("nifty_cash_long", "BUY", "nse_cm", "Cash NIFTY long (default)"),
        ("nifty_cash_short", "SELL", "nse_cm", "Cash NIFTY short (default)"),
    ],
}


def _now_ist() -> datetime:
    return datetime.now(IST)


def _atomic_write_json(path: Path, payload: dict) -> bool:
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        os.replace(tmp, path)
        return True
    except Exception as e:
        print(f"[strategy_selector] write failed: {e}", file=sys.stderr)
        return False


def _get_candidates(regime: str) -> list[tuple]:
    """Return list of candidate strategies for the given regime."""
    return CANDIDATES_BY_REGIME.get(regime, CANDIDATES_BY_REGIME["unknown"])


def _score_strategy(
    regime: str,
    strategy: str,
    side: str,
    segment: str,
    *,
    transaction_cost_pct: float = 0.10,
) -> dict:
    """Compute the data-driven score for one candidate.

    Score = win_rate * avg_gain_pct - (1 - win_rate) * avg_loss_pct - transaction_cost

    avg_gain_pct / avg_loss_pct are NORMALIZED to percent of position size
    (using ASSUMED_NOTIONAL=Rs.100,000 for rupees-to-percent conversion).

    Returns dict with: strategy, side, segment, score, ev_pct, win_rate,
                       n, source, has_data.
    """
    # Try local (regime, strategy) stats first
    from .online_learner import get_regime_strategy_stats
    local = get_regime_strategy_stats(regime, strategy)

    win_rate = local["win_rate"]
    n = local["n"]
    avg_pnl_rupees = local.get("avg_pnl", 0) or 0
    avg_win_rupees = local.get("avg_win", 0) or 0
    avg_loss_rupees = local.get("avg_loss", 0) or 0
    source = "local"

    # If n < MIN_N_FOR_DATA, fall back to Bayesian EV
    if n < MIN_N_FOR_DATA:
        from .bayesian_decision import decide
        try:
            bayes_d = decide(segment=segment)
            if side == "BUY":
                win_rate = bayes_d.get("win_rate_long", 0.5)
                bayes_ev = bayes_d.get("ev_long", 0)
            else:
                win_rate = bayes_d.get("win_rate_short", 0.5)
                bayes_ev = bayes_d.get("ev_short", 0)
            # Convert EV (in percent) to score components
            # Approximate: assume avg_gain and avg_loss are symmetric
            # Solve: p * G - (1-p) * L = EV, G+L=2, so G = 1 + EV/(2p-1)
            source = f"bayesian(fallback, n={n})"
            # Use bayes EV directly as score, mark has_data via Bayesian
            if win_rate > 0.5:
                est_avg_gain = 1.0 + bayes_ev / max(2 * win_rate - 1, 0.1)
                est_avg_loss = -1.0
            else:
                est_avg_gain = 0.5
                est_avg_loss = -1.0 + bayes_ev / max(1 - 2 * win_rate, 0.1)
            score = (win_rate * est_avg_gain +
                     (1 - win_rate) * est_avg_loss -
                     transaction_cost_pct)
            return {
                "strategy": strategy,
                "side": side,
                "segment": segment,
                "score": round(score, 4),
                "ev_pct": round(bayes_ev, 4),
                "win_rate": round(win_rate, 3),
                "n": n,
                "source": source,
                "has_data": n > 0,
                "fallback_to_bayesian": True,
            }
        except Exception:
            pass

    # We have enough local data — compute score from local stats
    # Convert rupees → percent of position size
    avg_pnl_pct = (avg_pnl_rupees / ASSUMED_NOTIONAL_PCT_CONV) * 100 if ASSUMED_NOTIONAL_PCT_CONV > 0 else 0
    avg_win_pct = (avg_win_rupees / ASSUMED_NOTIONAL_PCT_CONV) * 100 if ASSUMED_NOTIONAL_PCT_CONV > 0 else 0
    avg_loss_pct = (avg_loss_rupees / ASSUMED_NOTIONAL_PCT_CONV) * 100 if ASSUMED_NOTIONAL_PCT_CONV > 0 else 0

    # If win_rate known but no per-trade avg, estimate from win_rate and avg_pnl
    if (avg_win_pct == 0 and avg_loss_pct == 0 and n > 0):
        # avg_pnl = win_rate * avg_win + (1 - win_rate) * avg_loss
        # Assume avg_win = -2 * avg_loss (typical R:R)
        # avg_pnl = win_rate * (-2 * avg_loss) + (1 - win_rate) * avg_loss
        # avg_pnl = avg_loss * (-2 * win_rate + 1 - win_rate) = avg_loss * (1 - 3*win_rate)
        # avg_loss = avg_pnl / (1 - 3*win_rate)
        denom = 1 - 3 * win_rate
        if abs(denom) > 0.01:
            avg_loss_pct = avg_pnl_pct / denom
            avg_win_pct = -2 * avg_loss_pct

    # Score
    score = (win_rate * avg_win_pct +
             (1 - win_rate) * avg_loss_pct -
             transaction_cost_pct)

    return {
        "strategy": strategy,
        "side": side,
        "segment": segment,
        "score": round(score, 4),
        "ev_pct": round(avg_pnl_pct, 4),  # avg P&L per trade in %
        "win_rate": round(win_rate, 3),
        "n": n,
        "avg_win_pct": round(avg_win_pct, 3),
        "avg_loss_pct": round(avg_loss_pct, 3),
        "source": source,
        "has_data": True,
    }


def select_strategy(state: dict) -> dict:
    """Pick the best strategy for current market state.

    Args:
        state: dict with at least `regime`. Optional: `adx`, `rsi`, `vix`,
               `dist_from_vwap`, `vol_scaling`, etc.

    Returns:
        {
          "recommended": str (strategy name) | "hold",
          "side": "BUY" | "SELL",
          "segment": "nse_cm" | "nfo",
          "score": float,
          "candidates": [scored candidate dicts, sorted by score desc],
          "reason": str,
          "regime": str,
        }
    """
    regime = state.get("regime", "unknown")
    candidates = _get_candidates(regime)
    scored = []
    for strat, side, seg, desc in candidates:
        sc = _score_strategy(regime, strat, side, seg)
        sc["description"] = desc
        scored.append(sc)
    # Sort by score descending
    scored.sort(key=lambda x: x["score"], reverse=True)

    if not scored:
        return {
            "recommended": "hold",
            "reason": "no candidates",
            "regime": regime,
            "candidates": [],
        }

    best = scored[0]
    if best["score"] <= 0:
        return {
            "recommended": "hold",
            "reason": (f"best strategy '{best['strategy']}' has negative score "
                      f"({best['score']:+.3f}%); all candidates unprofitable"),
            "regime": regime,
            "candidates": scored,
            "best_score": best["score"],
        }

    return {
        "recommended": best["strategy"],
        "side": best["side"],
        "segment": best["segment"],
        "score": best["score"],
        "ev_pct": best.get("ev_pct", 0),
        "win_rate": best.get("win_rate", 0.5),
        "n": best.get("n", 0),
        "source": best.get("source", "unknown"),
        "reason": (f"data-driven: {best['strategy']} in {regime} regime "
                  f"has score {best['score']:+.3f}% "
                  f"(win={best.get('win_rate', 0.5)*100:.1f}%, n={best.get('n', 0)})"),
        "regime": regime,
        "candidates": scored,
    }


def get_selector_state_path() -> Path:
    return SELECTOR_STATE


def get_selection_context_for_prompt(state: dict) -> str:
    """Build a prompt-injectable block showing the data-driven candidates."""
    sel = select_strategy(state)
    lines = ["[DATA-DRIVEN STRATEGY SELECTOR — scored from history]"]
    if sel.get("regime"):
        lines.append(f"  Regime: {sel['regime']}")
    for i, c in enumerate(sel.get("candidates", [])[:4], 1):
        marker = " ← best" if i == 1 else ""
        n_str = f"n={c.get('n', 0)}" if c.get('n', 0) > 0 else "no local data"
        src = c.get("source", "?")
        lines.append(
            f"  {i}. {c['strategy']:24s} score={c['score']:+.3f}%  "
            f"win={c.get('win_rate', 0)*100:.1f}%  {n_str}  ({src}){marker}"
        )
    lines.append(f"  RECOMMENDED: {sel['recommended'].upper()}")
    if sel["recommended"] == "hold":
        lines.append(f"  Reason: {sel['reason']}")
    return "\n".join(lines)


if __name__ == "__main__":
    test_state = {
        "regime": "trending_up",
        "adx": 30,
        "rsi": 65,
        "vix": 14,
    }
    result = select_strategy(test_state)
    print(json.dumps(result, indent=2, default=str))