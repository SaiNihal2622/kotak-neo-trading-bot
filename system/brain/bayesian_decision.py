"""Bayesian decision engine — compute expected value per action.

PHASE 7 FINAL 2026-10-01: replaces boolean threshold checks with PROBABILISTIC
decisions based on empirical historical data.

The previous brain said: "ADX > 0.25 AND RSI > 60 AND VWAP > 0.10 → LONG".
That's a BOOLEAN rule. If true, OPEN. Else HOLD.

This module computes EXPECTED VALUE per action:
    E[LONG]  = P(profitable | LONG signal)  * avg_gain | win
              + (1 - P(profitable | LONG signal)) * avg_loss | lose
              - transaction_cost

    E[SHORT] = similar
    E[HOLD]  = 0  (no P&L, but no risk either)
    E[SHORT_more_size] = scale_size * E[SHORT]  (Kelly-like)

The brain picks the action with MAX expected value, not just "is signal true".

Sources of P(profitable):
1. Historical NIFTY daily (yfinance via signal_history.py)
2. Local trade_journal.jsonl outcomes
3. Combined via Bayesian update (with prior from yfinance, likelihood from journal)

If trade journal has 0 entries → use yfinance prior
If yfinance unavailable → fall back to priors derived from regime
"""

from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data_cache"

IST = timezone(timedelta(hours=5, minutes=30))

# PHASE 7 FIX 2026-10-01: assumed notional for converting local journal
# P&L (in rupees) to percent when merging with yfinance prior (in percent).
# This is the paper_capital — Rs.100,000. Used as the scaling denominator.
ASSUMED_NOTIONAL = 100_000.0


def _now_ist() -> datetime:
    return datetime.now(IST)


def _transaction_cost_pct(segment: str = "nse_cm") -> float:
    """Round-trip transaction cost as fraction of notional.

    NIFTY cash (nse_cm MIS): ~0.10% round trip
        - Brokerage: 0.03%
        - STT: 0.025% (sell side only, but conservatively counted both)
        - GST: ~0.005%
        - Exchange/SEBI: 0.005%
        - Slippage: ~0.05% (realistic for market orders)
    Total: ~0.10-0.15%
    """
    if segment == "nse_cm":
        return 0.10  # 10 bps for cash NIFTY
    if segment == "nfo":
        return 0.15  # 15 bps for options (STT is higher)
    return 0.10


def _fetch_yfinance_empirical(forward_days: int = 1) -> dict:
    """Fetch empirical signal stats from signal_history module."""
    try:
        from .signal_history import empirical_signal_stats, fetch_nifty_daily
        data = fetch_nifty_daily()
        if not data:
            return {"long": None, "short": None}
        return empirical_signal_stats(data, forward_days=forward_days)
    except Exception as e:
        print(f"[bayesian] yfinance empirical fetch failed: {e}", file=sys.stderr)
        return {"long": None, "short": None}


def _fetch_local_outcomes() -> dict:
    """Fetch trade outcomes from online_learner (preferred) or trade_journal.

    Returns:
        {
          "long":  {"win_rate": float, "n": int, "avg_pnl": float},
          "short": {"win_rate": float, "n": int, "avg_pnl": float}
        }

    PHASE 7 FINAL 2026-10-01: prefers online_learner.get_local_likelihood_for_bayesian()
    which reads learning_state.json (atomic, periodically refreshed). Falls
    back to raw journal parsing if online_learner unavailable.
    """
    out = {"long": {"win_rate": 0.5, "n": 0, "avg_pnl": 0.0},
           "short": {"win_rate": 0.5, "n": 0, "avg_pnl": 0.0}}
    # Preferred path: online_learner (learned state, not raw journal)
    try:
        from .online_learner import get_local_likelihood_for_bayesian
        long_like = get_local_likelihood_for_bayesian("BUY")
        short_like = get_local_likelihood_for_bayesian("SELL")
        out["long"] = {
            "win_rate": long_like.get("win_rate", 0.5),
            "n": long_like.get("n", 0),
            "avg_pnl": long_like.get("avg_gain", 0.0),
        }
        out["short"] = {
            "win_rate": short_like.get("win_rate", 0.5),
            "n": short_like.get("n", 0),
            "avg_pnl": short_like.get("avg_gain", 0.0),
        }
        if out["long"]["n"] + out["short"]["n"] >= 1:
            return out
    except Exception as e:
        print(f"[bayesian] online_learner fetch failed: {e}", file=sys.stderr)
    # Fallback: parse journal directly (older behavior)
    journal = DATA_DIR / "trade_journal.jsonl"
    if not journal.exists():
        return out
    long_pnls = []
    short_pnls = []
    try:
        for line in journal.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("event") != "FILL":
                continue
            side = rec.get("side", "").upper()
            pnl = float(rec.get("pnl", 0) or 0)
            if side == "BUY":
                long_pnls.append(pnl)
            elif side == "SELL":
                short_pnls.append(pnl)
    except Exception:
        pass
    if long_pnls:
        wins = sum(1 for p in long_pnls if p > 0)
        out["long"] = {
            "win_rate": wins / len(long_pnls),
            "n": len(long_pnls),
            "avg_pnl": sum(long_pnls) / len(long_pnls),
        }
    if short_pnls:
        wins = sum(1 for p in short_pnls if p > 0)
        out["short"] = {
            "win_rate": wins / len(short_pnls),
            "n": len(short_pnls),
            "avg_pnl": sum(short_pnls) / len(short_pnls),
        }
    return out


def bayesian_update(prior: dict, likelihood: dict, prior_weight: int = 50) -> dict:
    """Combine prior (yfinance historical) with likelihood (local journal).

    Uses Bayesian updating with a SMOOTHING WEIGHT on the prior. Without
    the smoothing weight, the local likelihood (often polluted by phantom
    fills in early sessions) completely dominates the prior. The default
    weight of 50 means the prior counts as ~50 virtual samples — the local
    data must accumulate 50+ real samples before it starts to dominate.

    All rates are normalized to 0-1 scale.

    Returns merged stats:
        {"win_rate": float (0-1), "avg_gain": float, "avg_loss": float, "n": int, "sharpe": float}
    """
    if not prior.get("n") or prior["n"] == 0:
        return likelihood
    if not likelihood.get("n") or likelihood["n"] == 0:
        return prior

    # Apply smoothing weight to prior (treat prior as if it has N+prior_weight samples)
    effective_prior_n = prior["n"] + prior_weight
    like_n = likelihood["n"]
    total_n = effective_prior_n + like_n

    prior_w = effective_prior_n / total_n
    like_w = like_n / total_n

    def _norm_win(v):
        if v is None:
            return 0.5
        if v > 1.0:
            return v / 100.0
        return v

    merged_win = _norm_win(prior["win_rate"]) * prior_w + _norm_win(likelihood["win_rate"]) * like_w
    merged_avg_gain = prior.get("avg_gain", 0) * prior_w + likelihood.get("avg_gain", 0) * like_w
    merged_avg_loss = prior.get("avg_loss", 0) * prior_w + likelihood.get("avg_loss", 0) * like_w
    merged_sharpe = prior.get("sharpe", 0) * prior_w + likelihood.get("sharpe", 0) * like_w

    return {
        "win_rate": round(merged_win, 4),
        "avg_gain": round(merged_avg_gain, 4),
        "avg_loss": round(merged_avg_loss, 4),
        "n": total_n,
        "sharpe": round(merged_sharpe, 2),
    }


def _norm_prior(v):
    """Normalize win_rate to 0-1."""
    if v is None:
        return 0.5
    if v > 1.0:
        return v / 100.0
    return v


def _norm_like(v):
    """Normalize win_rate to 0-1."""
    return _norm_prior(v)


def expected_value(merged: dict, side: str, transaction_cost_pct: float) -> float:
    """Compute expected value per share for a trade.

    EV = P(win) * avg_gain - (1 - P(win)) * avg_loss - transaction_cost
    """
    p_win = merged.get("win_rate", 0.5)
    avg_gain = merged.get("avg_gain", 0)
    avg_loss = merged.get("avg_loss", 0)  # negative
    if side == "long":
        ev = p_win * avg_gain + (1 - p_win) * avg_loss - transaction_cost_pct
    else:  # short
        ev = p_win * avg_gain + (1 - p_win) * avg_loss - transaction_cost_pct
    return ev


def decide(
    *,
    side: str = "both",
    segment: str = "nse_cm",
    use_local_journal: bool = True,
    min_n_for_local: int = 5,
) -> dict:
    """Compute decision EV per action (long / short / hold).

    Computes BOTH ev_long and ev_short in one call.
    Returns dict with ev_long, ev_short, ev_hold, recommended.
    """
    emp = _fetch_yfinance_empirical()
    cost = _transaction_cost_pct(segment)
    if not emp.get("long_signal") or emp["long_signal"].get("n", 0) == 0:
        return {"ev_long": 0, "ev_short": 0, "ev_hold": 0, "recommended": "hold",
                "win_rate_long": 0.5, "win_rate_short": 0.5, "n_prior_long": 0, "n_prior_short": 0,
                "sharpe_long": 0, "sharpe_short": 0, "transaction_cost_pct": cost}
    local = _fetch_local_outcomes() if use_local_journal else {"long": {"n": 0}, "short": {"n": 0}}
    def _build_merged(side_key):
        side_prior = emp.get(side_key + "_signal", {})
        side_local = local.get(side_key, {})
        win_rate = side_prior.get("win_rate", 50) / 100.0
        max_gain = side_prior.get("max_gain", 1) or 1
        max_loss = side_prior.get("max_loss", -1) or -1
        avg_gain_est = max(abs(max_gain) * 0.5, 0.005)
        avg_loss_est = abs(max_loss) * 0.5
        prior = {"win_rate": win_rate, "avg_gain": avg_gain_est, "avg_loss": -avg_loss_est,
                 "n": side_prior.get("n", 0), "sharpe": side_prior.get("sharpe", 0) or 0}
        if side_local.get("n", 0) >= min_n_for_local:
            # PHASE 7 FIX 2026-10-01: UNIT CONVERSION. Local journal P&L is
            # in RUPEES (realized_pnl field). yfinance prior is in PERCENT.
            # Convert rupees → percent by dividing by ASSUMED_NOTIONAL.
            # ASSUMED_NOTIONAL = paper_capital = Rs.100,000 (1 lot of NIFTY
            # at ~Rs.25000 spot × 75 shares is ~Rs.18.75L, but per-trade
            # notional depends on position size; we use the smaller paper
            # capital as a conservative scaling factor).
            local_avg_pnl_rupees = abs(side_local.get("avg_pnl", 0) or 0)
            local_pct = (local_avg_pnl_rupees / ASSUMED_NOTIONAL) * 100
            like = {"win_rate": side_local.get("win_rate", 0.5),
                    "avg_gain": max(local_pct * 0.5, 0.01),  # half of avg-rupees as pct
                    "avg_loss": -max(local_pct * 0.5, 0.01),
                    "n": side_local.get("n", 0), "sharpe": 0}
            return bayesian_update(prior, like)
        return prior
    merged_long = _build_merged("long")
    merged_short = _build_merged("short")
    ev_long = expected_value(merged_long, "long", cost)
    ev_short = expected_value(merged_short, "short", cost)
    ev_hold = 0.0
    if ev_long > 0 and ev_long > ev_short:
        recommended = "long"
    elif ev_short > 0 and ev_short > ev_long:
        recommended = "short"
    else:
        recommended = "hold"
    return {"ev_long": round(ev_long, 4), "ev_short": round(ev_short, 4),
            "ev_hold": ev_hold, "recommended": recommended,
            "win_rate_long": round(merged_long["win_rate"], 3),
            "win_rate_short": round(merged_short["win_rate"], 3),
            "n_prior_long": merged_long["n"], "n_prior_short": merged_short["n"],
            "sharpe_long": merged_long.get("sharpe"),
            "sharpe_short": merged_short.get("sharpe"),
            "transaction_cost_pct": cost}


def get_decision_context_for_prompt() -> str:
    """Build EV-decision context block for the brain prompt."""
    d = decide()
    if d["n_prior_long"] == 0:
        return ""

    lines = ["\n[BAYESIAN DECISION — expected value per action]"]
    lines.append(f"  E[LONG]  = {d['ev_long']:+.3f}% per share (win={d['win_rate_long']*100:.1f}%, sharpe={d.get('sharpe_long')}, n={d['n_prior_long']})")
    lines.append(f"  E[SHORT] = {d['ev_short']:+.3f}% per share (win={d['win_rate_short']*100:.1f}%, sharpe={d.get('sharpe_short')}, n={d['n_prior_short']})")
    lines.append(f"  E[HOLD]  = {d['ev_hold']:+.3f}% (no risk)")
    lines.append(f"  RECOMMENDED: {d['recommended'].upper()} (max EV)")
    lines.append(f"  Transaction cost: {d['transaction_cost_pct']:.2f}% round trip")
    return "\n".join(lines)


if __name__ == "__main__":
    print("[bayesian_decision] computing EV per action...")
    d_long = decide(side="long")
    d_short = decide(side="short")
    merged = {
        "ev_long": d_long["ev_long"],
        "ev_short": d_short["ev_short"],
        "ev_hold": 0,
        "recommended": "long" if d_long["ev_long"] > d_short["ev_short"] else "short",
        "win_rate_long": d_long["win_rate_long"],
        "win_rate_short": d_short["win_rate_short"],
        "n_prior_long": d_long["n_prior_long"],
        "n_prior_short": d_short["n_prior_short"],
        "sharpe_long": d_long.get("sharpe_long"),
        "sharpe_short": d_short.get("sharpe_short"),
        "transaction_cost_pct": d_long["transaction_cost_pct"],
    }
    print(json.dumps(merged, indent=2))
    print()
    print(get_decision_context_for_prompt())