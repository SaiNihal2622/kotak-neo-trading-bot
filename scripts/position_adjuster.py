"""Position adjuster — when a trade goes wrong, suggest adjustments.

For each open position, computes:
- Current P&L (mark to market)
- Distance to stop
- Time held
- Adjustments to consider:
  - Tighten stop (if move is going against us but we still believe in thesis)
  - Roll the position (if we have time and want to extend)
  - Close early (if thesis is broken)
  - Hedge (if delta exposure is too high)
  - Add to position (if conviction increases)

The LLM calls this helper to decide what to do with an open position.
"""
from __future__ import annotations
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
DATA = ROOT / 'data_cache'

sys.path.insert(0, str(ROOT / "scripts"))


def _read_json(path: Path, default=None) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default if default is not None else {}


def analyze_position(trade_id: str) -> dict:
    """Analyze a single open position. Returns:
       - current P&L (mark to market, rough)
       - distance to stop
       - time held
       - suggested actions
    """
    # Read trade from trades_state
    trades = _read_json(DATA / "trades_state.json", default={}).get("trades", {}) or {}
    if trade_id not in trades:
        return {"error": f"trade_id {trade_id} not found"}
    t = trades[trade_id]
    if t.get("status") != "open":
        return {"error": f"trade_id {trade_id} is not open (status={t.get('status')})"}
    plan = t.get("plan", {}) or {}
    underlying = t.get("underlying")
    legs = plan.get("legs", [])
    opened_at = t.get("opened_at")
    # Time held
    held_minutes = 0
    if opened_at:
        try:
            opened = datetime.fromisoformat(opened_at.replace("Z", "+00:00").replace("+00:00", ""))
            if opened.tzinfo:
                # Convert to naive for comparison
                opened_naive = opened.replace(tzinfo=None)
                held_minutes = (datetime.now() - opened_naive).total_seconds() / 60
            else:
                held_minutes = (datetime.now() - opened).total_seconds() / 60
        except Exception:
            held_minutes = 0
    # Current LTP (rough)
    candles = _read_json(DATA / "candles_aggregate.json", default={})
    ltp = (candles.get("symbols") or {}).get(underlying, {}).get("ltp", 0) or 0
    # P&L (rough: entry vs current premium)
    entry_premium = sum(
        (leg.get("price") or 0) * (1 if leg.get("side") == "BUY" else -1) * (leg.get("qty", 0))
        for leg in legs
    )
    # For sold positions, profit when price dropped
    # For bought positions, profit when price rose
    # Mark to market (approximation)
    current_value = 0
    entry_value = 0
    for leg in legs:
        # We don't have live option prices, so use a delta estimate from spot move
        spot_change = 0
        sess_open = (candles.get("symbols") or {}).get(underlying, {}).get("session_open")
        if sess_open and ltp:
            spot_change = (ltp - sess_open) / sess_open
        # Rough delta: ATM option moves ~50% of underlying move
        opt_delta = 0.5
        if leg.get("opt_type") == "PE":
            opt_delta = -0.5
        # Premium change estimate
        est_premium_change = spot_change * 100 * opt_delta  # rough (in rupees, per share)
        leg_premium = leg.get("price") or 50
        current_leg_premium = max(0, leg_premium + est_premium_change)
        if leg.get("side") == "BUY":
            current_value += current_leg_premium * leg.get("qty", 0) * 30  # rough lot
            entry_value += leg_premium * leg.get("qty", 0) * 30
        else:
            current_value -= current_leg_premium * leg.get("qty", 0) * 30
            entry_value -= leg_premium * leg.get("qty", 0) * 30
    pnl_estimate = current_value - entry_value
    # Time-in-trade checks
    max_hold = plan.get("max_hold_minutes") or plan.get("expected_hold_minutes") or 240
    time_remaining = max_hold - held_minutes
    # Suggested actions
    actions = []
    if pnl_estimate < -500:
        actions.append({
            "action": "tighten_stop",
            "reason": f"P&L is {pnl_estimate:+,.0f} (loss > 500). Consider tightening stop to lock in remaining capital.",
        })
    if pnl_estimate > 1000:
        actions.append({
            "action": "take_partial_profit",
            "reason": f"P&L is +{pnl_estimate:,.0f} (gain > 1000). Consider taking 50% off to lock in gains.",
        })
    if time_remaining < 30 and time_remaining > 0:
        actions.append({
            "action": "close_soon",
            "reason": f"Only {time_remaining:.0f} min remaining in max_hold. If thesis still valid, consider rolling. If not, close now.",
        })
    if time_remaining <= 0:
        actions.append({
            "action": "close_now",
            "reason": f"Max hold time exceeded ({held_minutes:.0f} > {max_hold} min). Close position now.",
        })
    # Stop check
    target = plan.get("target")
    stop = plan.get("stop")
    if stop and ltp and underlying:
        # Approximate position stop price
        actions.append({
            "action": "monitor_stop",
            "stop_price": stop,
            "current_spot": ltp,
            "note": f"Position stop is at premium {stop}. If premium hits this, close.",
        })
    return {
        "trade_id": trade_id,
        "underlying": underlying,
        "strategy": plan.get("strategy"),
        "held_minutes": round(held_minutes, 1),
        "time_remaining_minutes": round(time_remaining, 1),
        "max_hold_minutes": max_hold,
        "pnl_estimate_rs": round(pnl_estimate, 2),
        "current_spot": ltp,
        "target": target,
        "stop": stop,
        "suggested_actions": actions,
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python position_adjuster.py <trade_id>")
        sys.exit(1)
    print(json.dumps(analyze_position(sys.argv[1]), indent=2, default=str))
