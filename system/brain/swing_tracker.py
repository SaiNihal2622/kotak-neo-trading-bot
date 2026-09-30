"""Swing position tracker — multi-day holds with target/stop/time exits.

PHASE 6 FIX 2026-09-30 (swing mode): when KOTAK_ENABLE_SWING=1, the brain
can open nifty_swing_long/short positions with `swing: true` flag.
These positions bypass the 15:15 EOD close. This module tracks them
across days:

  - Open: when brain fires SWING_OPEN (action=OPEN + strategy in swing_* + swing=true)
  - Track: write entry metadata (target/stop/hold_days/entry_ts/entry_price)
  - Exit: target hit, stop hit, or hold_days exceeded (auto-close)

File: data_cache/swing_positions.json

Schema:
  {
    "nifty_swing_long_<ts>": {
      "strategy": "nifty_swing_long",
      "underlying": "NIFTY",
      "side": "BUY",
      "qty": 75,
      "entry_price": 22700,
      "entry_ts": "2026-09-30T11:30:00+05:30",
      "target_pct": 0.02,
      "stop_pct": 0.015,
      "hold_days": 5,
      "current_price": 22750,    # updated each cycle
      "current_pnl": 1750,       # updated each cycle
      "current_pnl_pct": 0.0077,
      "status": "open",          # open | stopped_out | target_hit | time_exited
    }
  }

The brain daemon's cycle() calls check_swing_exits() on every iteration
AFTER the main decision. If exit fires, brain writes SWING_CLOSE action.

PHASE 6 FIX 2026-09-30: this module is opt-in (KOTAK_ENABLE_SWING=1).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

from .brain_daemon import _now_ist

IST = timezone(timedelta(hours=5, minutes=30))
DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data_cache"
SWING_FILE = DATA_DIR / "swing_positions.json"


def _load_swing() -> list[dict]:
    if not SWING_FILE.exists():
        return []
    try:
        data = json.loads(SWING_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return list(data.values())
    except Exception:
        return []
    return []


def _save_swing(positions: list[dict]) -> None:
    SWING_FILE.parent.mkdir(parents=True, exist_ok=True)
    SWING_FILE.write_text(json.dumps(positions, indent=2, ensure_ascii=False), encoding="utf-8")


def add_swing_position(
    *,
    strategy: str,
    underlying: str,
    side: str,
    qty: int,
    entry_price: float,
    target_pct: float,
    stop_pct: float,
    hold_days: int,
) -> dict:
    """Add a new swing position to track."""
    pos = {
        "strategy": strategy,
        "underlying": underlying,
        "side": side,
        "qty": qty,
        "entry_price": entry_price,
        "entry_ts": _now_ist().isoformat(),
        "target_pct": target_pct,
        "stop_pct": stop_pct,
        "hold_days": hold_days,
        "current_price": entry_price,
        "current_pnl": 0.0,
        "current_pnl_pct": 0.0,
        "status": "open",
    }
    positions = _load_swing()
    positions.append(pos)
    _save_swing(positions)
    return pos


def update_swing_prices(ltp_by_underlying: dict[str, float]) -> None:
    """Update current_price + current_pnl for all open swing positions."""
    positions = _load_swing()
    changed = False
    for p in positions:
        if p.get("status") != "open":
            continue
        u = p.get("underlying", "")
        ltp = ltp_by_underlying.get(u)
        if ltp is None or ltp <= 0:
            continue
        entry = p.get("entry_price", 0)
        qty = p.get("qty", 0)
        side = p.get("side", "BUY")
        if side == "BUY":
            pnl = (ltp - entry) * qty
            pnl_pct = (ltp - entry) / entry if entry else 0
        else:
            pnl = (entry - ltp) * qty
            pnl_pct = (entry - ltp) / entry if entry else 0
        p["current_price"] = ltp
        p["current_pnl"] = round(pnl, 2)
        p["current_pnl_pct"] = round(pnl_pct, 4)
        changed = True
    if changed:
        _save_swing(positions)


def check_swing_exits() -> list[dict]:
    """Check if any open swing position hit target/stop/time exit.

    Returns list of positions that should be closed (caller writes
    SWING_CLOSE action via brain daemon).
    """
    now = _now_ist()
    positions = _load_swing()
    to_close = []
    for p in positions:
        if p.get("status") != "open":
            continue
        target_pct = float(p.get("target_pct", 0.02))
        stop_pct = float(p.get("stop_pct", 0.015))
        hold_days = int(p.get("hold_days", 5))
        pnl_pct = float(p.get("current_pnl_pct", 0))
        entry_ts_str = p.get("entry_ts", "")
        try:
            entry_ts = datetime.fromisoformat(entry_ts_str.replace("Z", "+00:00"))
            if entry_ts.tzinfo is None:
                entry_ts = entry_ts.replace(tzinfo=IST)
            else:
                entry_ts = entry_ts.astimezone(IST)
        except Exception:
            continue
        days_held = (now.date() - entry_ts.date()).days

        exit_reason = None
        if pnl_pct >= target_pct:
            exit_reason = f"target_hit (+{pnl_pct*100:.2f}% >= +{target_pct*100:.2f}%)"
        elif pnl_pct <= -stop_pct:
            exit_reason = f"stopped_out ({pnl_pct*100:.2f}% <= -{stop_pct*100:.2f}%)"
        elif days_held >= hold_days:
            exit_reason = f"time_exited ({days_held}d >= {hold_days}d)"

        if exit_reason:
            p["status"] = exit_reason.split(" ")[0]  # "target_hit"/"stopped_out"/"time_exited"
            p["exit_ts"] = now.isoformat()
            p["exit_reason"] = exit_reason
            to_close.append(p)
    if to_close:
        _save_swing(positions)
    return to_close


def get_open_swings() -> list[dict]:
    """Return open swing positions."""
    return [p for p in _load_swing() if p.get("status") == "open"]


def close_swing(strategy: str, underlying: str, reason: str) -> bool:
    """Mark a swing position as closed (called after SWING_CLOSE fills)."""
    positions = _load_swing()
    changed = False
    for p in positions:
        if p.get("status") == "open" and p.get("strategy") == strategy and p.get("underlying") == underlying:
            p["status"] = reason
            p["exit_ts"] = _now_ist().isoformat()
            changed = True
    if changed:
        _save_swing(positions)
    return changed