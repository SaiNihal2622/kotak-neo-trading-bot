"""Adaptive exits — derive target/stop from empirical avg_gain/avg_loss.

PHASE 8 (2026-10-01): the OLD code had hardcoded
  target = 1.0  # %
  stop = 0.75   # %
  swing_target = 0.02  # 2%
  swing_stop = 0.015   # 1.5%

The NEW adaptive exits set target/stop from the strategy's historical
avg_gain (target) and avg_loss (stop), with sensible scaling.

RATIONALE:
- If strategy historically wins +1.5%, target = 1.0% (capture 67%)
  lets winners run partially without giving back gains.
- If strategy historically loses -1.0%, stop = 1.2% (cut at 120% of
  typical loss) — slightly worse than typical loss to avoid whipsaw,
  but tighter than letting a full loss run.
- For multi-day swings, use swing_avg_gain/avg_loss (typically larger).

VOLATILITY ADJUSTMENT:
- Higher realized vol → wider stops (avoid noise stop-outs)
- Lower realized vol → tighter stops (cut quickly)

DEFAULTS (cold start, no data):
- intraday: target = 0.8%, stop = 0.6%
- swing: target = 2.0%, stop = 1.5%

WATCH FOR:
- Stop too tight → frequent whipsaw stop-outs (loses money)
- Stop too wide → full loss runs (catastrophic)
- Target too tight → leaves money on table
- Target too wide → winners turn into losers

The scaling factors (target_scale=0.7, stop_scale=1.2) come from
"capture 70% of typical gain, cut at 120% of typical loss" — a
sensible middle ground.
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

# How much of typical gain to capture as target
TARGET_SCALE = 0.7
# How wide the stop should be (multiplier of typical loss)
STOP_SCALE = 1.2
# Floor/ceiling to prevent degenerate exits
MIN_INTRADAY_TARGET = 0.3   # %
MAX_INTRADAY_TARGET = 2.5
MIN_INTRADAY_STOP = 0.2
MAX_INTRADAY_STOP = 1.5
MIN_SWING_TARGET = 1.0
MAX_SWING_TARGET = 5.0
MIN_SWING_STOP = 0.5
MAX_SWING_STOP = 3.0

# Defaults when no historical data
DEFAULT_INTRADAY_TARGET = 0.8
DEFAULT_INTRADAY_STOP = 0.6
DEFAULT_SWING_TARGET = 2.0
DEFAULT_SWING_STOP = 1.5

ASSUMED_NOTIONAL = 100_000.0


def _now_ist() -> datetime:
    return datetime.now(IST)


def compute_exits(
    *,
    avg_gain_rupees: float = 0.0,
    avg_loss_rupees: float = 0.0,
    realized_vol_pct: float = 10.0,
    target_vol_pct: float = 12.0,
    is_swing: bool = False,
) -> dict:
    """Compute adaptive target/stop from empirical gain/loss.

    Args:
        avg_gain_rupees: average winning trade P&L in rupees (positive)
        avg_loss_rupees: average losing trade P&L in rupees (positive magnitude)
        realized_vol_pct: current realized volatility (annualized %)
        target_vol_pct: target vol for normalization
        is_swing: True for multi-day swing trades (different defaults/ranges)

    Returns:
        {
          "target_pct": float (% gain to capture),
          "stop_pct": float (% loss to cut at),
          "target_rupees": float (absolute target for Rs.100k position),
          "stop_rupees": float (absolute stop for Rs.100k position),
          "vol_scale": float (vol adjustment factor),
          "reason": str,
        }
    """
    if is_swing:
        min_t, max_t = MIN_SWING_TARGET, MAX_SWING_TARGET
        min_s, max_s = MIN_SWING_STOP, MAX_SWING_STOP
        default_t = DEFAULT_SWING_TARGET
        default_s = DEFAULT_SWING_STOP
    else:
        min_t, max_t = MIN_INTRADAY_TARGET, MAX_INTRADAY_TARGET
        min_s, max_s = MIN_INTRADAY_STOP, MAX_INTRADAY_STOP
        default_t = DEFAULT_INTRADAY_TARGET
        default_s = DEFAULT_INTRADAY_STOP

    # Convert rupees → percent of notional
    if avg_gain_rupees > 0:
        avg_gain_pct = (avg_gain_rupees / ASSUMED_NOTIONAL) * 100
    else:
        avg_gain_pct = 0
    if avg_loss_rupees > 0:
        avg_loss_pct = (avg_loss_rupees / ASSUMED_NOTIONAL) * 100
    else:
        avg_loss_pct = 0

    # Vol scaling: higher vol → wider stops
    if realized_vol_pct > 0:
        vol_scale = math.sqrt(realized_vol_pct / target_vol_pct)
    else:
        vol_scale = 1.0
    vol_scale = max(0.7, min(2.0, vol_scale))

    # Compute target
    if avg_gain_pct > 0:
        target_pct = avg_gain_pct * TARGET_SCALE * vol_scale
    else:
        target_pct = default_t
    target_pct = max(min_t, min(max_t, target_pct))

    # Compute stop
    if avg_loss_pct > 0:
        stop_pct = avg_loss_pct * STOP_SCALE * vol_scale
    else:
        stop_pct = default_s
    stop_pct = max(min_s, min(max_s, stop_pct))

    return {
        "target_pct": round(target_pct, 3),
        "stop_pct": round(stop_pct, 3),
        "target_rupees": round(target_pct / 100 * ASSUMED_NOTIONAL, 2),
        "stop_rupees": round(stop_pct / 100 * ASSUMED_NOTIONAL, 2),
        "vol_scale": round(vol_scale, 3),
        "avg_gain_pct": round(avg_gain_pct, 3),
        "avg_loss_pct": round(avg_loss_pct, 3),
        "is_swing": is_swing,
        "reason": (
            f"avg_gain={avg_gain_pct:.2f}% → target={target_pct:.2f}% "
            f"(scale={TARGET_SCALE}×vol={vol_scale:.2f}); "
            f"avg_loss={avg_loss_pct:.2f}% → stop={stop_pct:.2f}% "
            f"(scale={STOP_SCALE}×vol={vol_scale:.2f})"
        ),
    }


def exits_for_strategy(
    regime: str,
    strategy: str,
    *,
    realized_vol_pct: float = 10.0,
    is_swing: bool = False,
) -> dict:
    """Compute exits for a strategy using local (regime, strategy) stats.

    Falls back to overall strategy stats, then to defaults.
    """
    from .online_learner import get_regime_strategy_stats
    local = get_regime_strategy_stats(regime, strategy)
    avg_gain = abs(local.get("avg_win", 0) or 0)
    avg_loss = abs(local.get("avg_loss", 0) or 0)
    n = local.get("n", 0)
    source = "local"

    if n < 3 or (avg_gain == 0 and avg_loss == 0):
        # Try overall strategy stats
        from .online_learner import get_strategy_performance
        overall = get_strategy_performance(strategy)
        if overall.get("n", 0) >= 3:
            avg_gain = abs(overall.get("avg_win", 0) or 0)
            avg_loss = abs(overall.get("avg_loss", 0) or 0)
            source = "strategy_overall"

    if avg_gain == 0 and avg_loss == 0:
        source = "default"

    result = compute_exits(
        avg_gain_rupees=avg_gain,
        avg_loss_rupees=avg_loss,
        realized_vol_pct=realized_vol_pct,
        is_swing=is_swing,
    )
    result["strategy"] = strategy
    result["regime"] = regime
    result["source"] = source
    result["n_local"] = n
    return result


def get_exits_context_for_prompt(state: dict) -> str:
    """Build a prompt-injectable exits summary for current state."""
    regime = state.get("regime", "unknown")
    realized_vol = state.get("realized_vol_pct", 10.0)

    from .strategy_selector import _get_candidates
    candidates = _get_candidates(regime)
    lines = ["[ADAPTIVE EXITS — target/stop from empirical gain/loss]"]
    for strat, side, seg, desc in candidates[:3]:
        is_swing = "swing" in strat
        ex = exits_for_strategy(regime, strat, realized_vol_pct=realized_vol, is_swing=is_swing)
        lines.append(
            f"  {strat:24s}: target=+{ex['target_pct']:.2f}% "
            f"(~Rs.{ex['target_rupees']:.0f}) / "
            f"stop=-{ex['stop_pct']:.2f}% (~Rs.{ex['stop_rupees']:.0f}) "
            f"[{ex['source']}, n={ex['n_local']}]"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    import math
    # Example: historical avg_gain=Rs.1500, avg_loss=Rs.1000, realized_vol=10%
    print(json.dumps(compute_exits(
        avg_gain_rupees=1500.0,
        avg_loss_rupees=1000.0,
        realized_vol_pct=10.0,
        is_swing=False,
    ), indent=2))
    print()
    print(json.dumps(exits_for_strategy("trending_up", "nifty_cash_long"), indent=2))