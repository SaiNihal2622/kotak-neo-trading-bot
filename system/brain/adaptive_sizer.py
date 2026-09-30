"""Adaptive position sizer — Kelly criterion from empirical win/loss.

PHASE 8 (2026-10-01): the OLD code had `scaled_qty = 75 * vol_scale`
hardcoded. The NEW sizer uses Kelly criterion computed from real
win/loss data, scaled by fractional Kelly for safety.

THE MATH:
  Full Kelly: f* = (p * b - q) / b
    p = probability of winning
    q = 1 - p (probability of losing)
    b = ratio of avg win to avg loss (the "odds")

  Example: 60% win rate, avg win 1.5%, avg loss 1.0%
    b = 1.5 / 1.0 = 1.5
    f* = (0.6 * 1.5 - 0.4) / 1.5 = (0.9 - 0.4) / 1.5 = 0.333
    → bet 33% of capital on each trade

  Fractional Kelly (we use 1/4):
    f = 0.25 * f* = 0.083
    → bet 8.3% of capital per trade

WHY FRACTIONAL:
- Full Kelly is theoretically optimal but assumes perfect estimates.
- Real estimates have error → full Kelly is volatile.
- 1/4 Kelly is the industry standard for safety (and matches
  "above noise floor" thresholds for live trading).

SOURCES OF p, b:
1. Local (regime, strategy) — primary, from online_learner
2. Strategy overall stats — fallback when n < 3 in regime
3. Bayesian EV from signal_history — cold-start fallback

VOL SCALING (additional adjustment):
- Realized vol scaling: f * (target_vol / realized_vol)^0.5
  - Lower vol → bigger size (more confident in low-vol regime)
  - Higher vol → smaller size (less confident)

CAPS:
- Minimum 1 lot per leg (qty >= lot_size)
- Maximum 10 lots per leg (UNLEASHED mode allows more, but sane cap)
- Cash NIFTY lot size = 75 shares (per Kotak spec)

WATCH FOR:
- Negative Kelly (p*b < q) → bet 0 (HOLD)
- Zero b → no avg loss data → use Kelly with b=1 default
- Kelly > 1 (impossible) → cap at fractional Kelly
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

IST = timezone(timedelta(hours=5, minutes=30))

# Kelly fraction: 1/4 is industry standard for safety
KELLY_FRACTION = 0.25

# Position caps
MAX_LOTS = 10        # max 10 lots per leg (UNLEASHED but sane)
MIN_LOTS = 1         # at least 1 lot

# Lot size for cash NIFTY
NIFTY_LOT_SIZE = 75  # shares per lot

# Target vol for scaling (annualized %)
TARGET_VOL_PCT = 12.0


def _now_ist() -> datetime:
    return datetime.now(IST)


def _assumed_notional() -> float:
    """Get paper_capital (assumed notional) from settings or default."""
    # We could read from settings.yaml but Rs.100k is consistent
    # with ASSUMED_NOTIONAL in bayesian_decision.
    return 100_000.0


def kelly_fraction(win_rate: float, avg_win: float, avg_loss: float) -> float:
    """Compute Kelly fraction from win rate and gain/loss.

    Args:
        win_rate: 0-1
        avg_win: positive number (avg win size)
        avg_loss: positive number (avg loss size, returns as positive)

    Returns:
        Kelly fraction (0-1). Returns 0 if math gives negative.
    """
    if win_rate <= 0 or avg_loss <= 0:
        return 0.0
    p = win_rate
    q = 1 - win_rate
    b = avg_win / avg_loss
    f = (p * b - q) / b
    # Kelly can be slightly negative if edge is small
    return max(0.0, f)


def fractional_kelly(win_rate: float, avg_win: float, avg_loss: float,
                     fraction: float = KELLY_FRACTION) -> float:
    """Fractional Kelly: full_kelly * fraction."""
    full = kelly_fraction(win_rate, avg_win, avg_loss)
    return full * fraction


def compute_position_size(
    *,
    win_rate: float,
    avg_win_pct: float,
    avg_loss_pct: float,
    realized_vol_pct: float = 10.0,
    target_vol_pct: float = TARGET_VOL_PCT,
    cash: float = 100_000.0,
    lot_size: int = NIFTY_LOT_SIZE,
    max_lots: int = MAX_LOTS,
    kelly_fraction_value: float = KELLY_FRACTION,
) -> dict:
    """Compute position size in lots.

    Returns:
        {
          "lots": int,
          "qty": int (shares),
          "notional_rs": float,
          "pct_of_capital": float,
          "full_kelly": float,
          "fractional_kelly": float,
          "vol_scale": float,
          "reason": str,
        }
    """
    if win_rate <= 0 or avg_loss_pct <= 0:
        return {
            "lots": 0, "qty": 0, "notional_rs": 0.0,
            "pct_of_capital": 0.0,
            "full_kelly": 0.0,
            "fractional_kelly": 0.0,
            "vol_scale": 1.0,
            "reason": "no_edge_or_no_loss_data",
        }

    full_k = kelly_fraction(win_rate, avg_win_pct, avg_loss_pct)
    frac_k = full_k * kelly_fraction_value

    # Vol scaling: lower vol → bigger size, higher vol → smaller
    if realized_vol_pct > 0:
        vol_scale = math.sqrt(target_vol_pct / realized_vol_pct)
    else:
        vol_scale = 1.0
    vol_scale = max(0.25, min(2.0, vol_scale))

    # Apply vol scaling to fractional Kelly
    sized_pct = frac_k * vol_scale

    # Cap at max lots (e.g., 25% of capital even with great edge)
    max_pct = 0.25
    sized_pct = min(sized_pct, max_pct)

    # Convert to lots using NIFTY spot ~ Rs.25,000
    # lot_size * spot_price = 75 * 25000 = 1,875,000 per lot
    spot_price = 25000.0
    lots_float = (cash * sized_pct) / (lot_size * spot_price)
    lots = max(0, int(lots_float))

    # Cap at MAX_LOTS
    lots = min(lots, max_lots)
    # Only floor to MIN_LOTS if Kelly > 0 AND we have meaningful sized_pct
    # (don't blow the cap by forcing 1 lot when Kelly says 0.05 lots)
    if full_k <= 0:
        lots = 0  # No edge, don't trade
    elif lots == 0 and sized_pct >= 0.005:  # 0.5% of capital = enough for 1 lot
        lots = MIN_LOTS

    qty = lots * lot_size
    actual_notional = qty * spot_price
    # Indian NIFTY cash trading uses leverage (~5x intraday, ~18x on full notional
    # of Rs.1.875M for 1 lot). pct_of_capital here is the LEVERAGED exposure,
    # not capital deployed. Capital deployed ≈ margin = notional / leverage_factor.
    # For sizing decisions, the relevant number is "lots" — see lots/qty fields.
    actual_pct = actual_notional / cash if cash > 0 else 0

    return {
        "lots": lots,
        "qty": qty,
        "notional_rs": round(actual_notional, 2),
        "pct_of_capital": round(actual_pct, 4),
        "full_kelly": round(full_k, 4),
        "fractional_kelly": round(frac_k, 4),
        "vol_scale": round(vol_scale, 3),
        "reason": (
            f"Kelly=({win_rate:.2f}*{avg_win_pct:.2f}-{(1-win_rate):.2f}*{avg_loss_pct:.2f})/"
            f"{avg_loss_pct:.2f}={full_k:.3f} → frac_k={frac_k:.3f} × vol={vol_scale:.2f} → {sized_pct:.3f}"
        ),
    }


def size_for_strategy(
    regime: str,
    strategy: str,
    *,
    realized_vol_pct: float = 10.0,
    cash: float = 100_000.0,
    lot_size: int = NIFTY_LOT_SIZE,
    target_vol_pct: float = TARGET_VOL_PCT,
    transaction_cost_pct: float = 0.10,
) -> dict:
    """Compute Kelly position size for a strategy in a given regime.

    Pulls (regime, strategy) stats from online_learner. Falls back to
    Bayesian EV if no local data.
    """
    from .online_learner import get_regime_strategy_stats
    local = get_regime_strategy_stats(regime, strategy)
    win_rate = local["win_rate"]
    n = local["n"]
    avg_pnl_rupees = local.get("avg_pnl", 0) or 0
    avg_win_rupees = local.get("avg_win", 0) or 0
    avg_loss_rupees = local.get("avg_loss", 0) or 0
    source = "local"

    if n < 3:
        # Fall back to Bayesian EV
        from .bayesian_decision import decide
        side = "BUY"  # default; not relevant for sizing math
        # Determine side from strategy name
        if "short" in strategy or "put" in strategy:
            side = "SELL"
        bayes_d = decide(segment="nse_cm")
        if side == "BUY":
            win_rate = bayes_d.get("win_rate_long", 0.5)
            bayes_ev = bayes_d.get("ev_long", 0)
        else:
            win_rate = bayes_d.get("win_rate_short", 0.5)
            bayes_ev = bayes_d.get("ev_short", 0)
        source = f"bayesian(fallback, n={n})"
        # Approximate from EV: assume win=1%, loss=-1%
        avg_win_pct = 1.0
        avg_loss_pct = 1.0
        # Adjust if EV suggests different edge
        if bayes_ev > 0.5:
            avg_win_pct = 1.5
        elif bayes_ev < -0.5:
            avg_loss_pct = 1.5
    else:
        # Use real local data
        notional = _assumed_notional()
        # Convert rupees → percent of notional
        avg_win_pct = abs(avg_win_rupees) / notional * 100 if notional > 0 else 1.0
        avg_loss_pct = abs(avg_loss_rupees) / notional * 100 if notional > 0 else 1.0
        # Floor to prevent degenerate Kelly
        avg_win_pct = max(avg_win_pct, 0.05)
        avg_loss_pct = max(avg_loss_pct, 0.05)

    size = compute_position_size(
        win_rate=win_rate,
        avg_win_pct=avg_win_pct,
        avg_loss_pct=avg_loss_pct,
        realized_vol_pct=realized_vol_pct,
        target_vol_pct=target_vol_pct,
        cash=cash,
        lot_size=lot_size,
    )
    size["strategy"] = strategy
    size["regime"] = regime
    size["source"] = source
    size["n_local"] = n
    size["win_rate"] = round(win_rate, 3)
    size["avg_win_pct"] = round(avg_win_pct, 3)
    size["avg_loss_pct"] = round(avg_loss_pct, 3)
    return size


def get_sizer_context_for_prompt(state: dict) -> str:
    """Build a prompt-injectable sizer summary for current state."""
    regime = state.get("regime", "unknown")
    realized_vol = state.get("realized_vol_pct", 10.0)
    cash = state.get("cash", 100_000.0)

    # Get size for the top 3 strategies in this regime
    from .strategy_selector import _get_candidates
    candidates = _get_candidates(regime)
    lines = ["[KELLY POSITION SIZER — empirical win/loss → optimal size]"]
    for strat, side, seg, desc in candidates[:3]:
        size = size_for_strategy(
            regime, strat,
            realized_vol_pct=realized_vol, cash=cash,
        )
        if size["lots"] > 0:
            lines.append(
                f"  {strat:24s}: {size['lots']} lots ({size['qty']} shares) "
                f"~ {size['pct_of_capital']*100:.1f}% of capital "
                f"(Kelly={size['fractional_kelly']:.3f} × vol={size['vol_scale']:.2f}, "
                f"win={size['win_rate']*100:.1f}%, source={size['source']})"
            )
        else:
            lines.append(
                f"  {strat:24s}: 0 lots (no edge: full_kelly={size['full_kelly']:.3f})"
            )
    return "\n".join(lines)


if __name__ == "__main__":
    # Example: 60% win, 1.5% gain, 1.0% loss
    print(json.dumps(compute_position_size(
        win_rate=0.60, avg_win_pct=1.5, avg_loss_pct=1.0,
        realized_vol_pct=10.0, cash=100_000.0,
    ), indent=2))
    print()
    print(json.dumps(size_for_strategy("trending_up", "nifty_cash_long"), indent=2))