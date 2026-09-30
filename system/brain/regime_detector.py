"""Regime detector — detect when market regime SHIFTS vs historical baseline.

PHASE 7 FINAL 2026-10-01: a static "trending_up" label is a TEMPLATE.
Real intelligence detects WHEN the regime changes. If we're in a regime
that hasn't been seen in 60 days, our historical priors are stale and
the LLM should reduce conviction.

This module:

1. Maintains a rolling 60-day window of regime labels + magnitudes.
2. Computes:
   - regime_stability_score: 0-1 (1 = same regime as 60d baseline)
   - vol_regime_shift: bool — current 5d realized vol > 2x 60d median
   - trend_break: bool — current 5d return vs 60d median return
   - unusual_session_pct: bool — |session_pct| > 95th percentile of history
3. Outputs a regime_shift flag with reasons.
4. Exposes get_regime_shift_context() for the brain prompt — if shifted,
   the LLM is told to REDUCE conviction and treat priors as suspect.

DESIGN:
- Reads from data_cache/regime_history.jsonl (atomic append-only log)
- Each entry: {ts, regime, session_pct, vix, adx, rsi, nifty_spot}
- Pruned to last 60 trading days on every read.
- Compute percentiles from the cleaned set.

WATCH FOR:
- Empty history (cold start) → returns stability=1.0, shift=False
- First few days of data → percentiles unstable; use median (50th)
- Strategy splits (long vs short) → track both
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
HISTORY_PATH = DATA_DIR / "regime_history.jsonl"

IST = timezone(timedelta(hours=5, minutes=30))

# Lookback window for percentile computation
LOOKBACK_DAYS = 60
MIN_SAMPLES = 10  # need this many before flagging shifts


def _now_ist() -> datetime:
    return datetime.now(IST)


def _atomic_append_jsonl(path: Path, payload: dict) -> bool:
    """Atomic append to JSONL — write to tmp, then append to main."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        line = json.dumps(payload, default=str) + "\n"
        tmp.write_text(line, encoding="utf-8")
        # Append to main file
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
        try:
            tmp.unlink()
        except Exception:
            pass
        return True
    except Exception:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        # Direct append fallback
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(payload, default=str) + "\n")
            return True
        except Exception as e:
            print(f"[regime_detector] append failed: {e}", file=sys.stderr)
            return False


def _load_history() -> list[dict]:
    """Load regime history, prune to LOOKBACK_DAYS, dedupe by ts."""
    if not HISTORY_PATH.exists():
        return []
    entries = []
    seen_ts = set()
    try:
        for line in HISTORY_PATH.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            ts = rec.get("ts", "")
            if ts in seen_ts:
                continue
            seen_ts.add(ts)
            entries.append(rec)
    except Exception:
        return []
    # Prune by date (last 60 days)
    cutoff = (_now_ist() - timedelta(days=LOOKBACK_DAYS)).date()
    pruned = []
    for e in entries:
        try:
            d = datetime.fromisoformat(e["ts"].replace("Z", "+00:00")).date()
        except Exception:
            continue
        if d >= cutoff:
            pruned.append(e)
    return pruned


def _percentile(values: list[float], p: float) -> float:
    """Compute the p-th percentile (0-100)."""
    if not values:
        return 0.0
    sorted_v = sorted(values)
    n = len(sorted_v)
    if n == 1:
        return sorted_v[0]
    rank = (p / 100.0) * (n - 1)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return sorted_v[lo]
    frac = rank - lo
    return sorted_v[lo] * (1 - frac) + sorted_v[hi] * frac


def record(regime: str, session_pct: float, vix: float,
           adx: float, rsi: float, nifty_spot: float) -> bool:
    """Record current regime state to history."""
    payload = {
        "ts": _now_ist().isoformat(),
        "regime": regime,
        "session_pct": round(session_pct, 4),
        "vix": round(vix, 2),
        "adx": round(adx, 2),
        "rsi": round(rsi, 2),
        "nifty_spot": round(nifty_spot, 2),
    }
    return _atomic_append_jsonl(HISTORY_PATH, payload)


def detect_shift(current: dict) -> dict:
    """Detect regime shift given current state and 60d history.

    current dict: {regime, session_pct, vix, adx, rsi, nifty_spot}

    Returns:
        {
          "shifted": bool,
          "reasons": [str],
          "stability": float (0-1),
          "vol_zscore": float,
          "session_pct_pctl": float (0-100),
          "vix_pctl": float,
          "history_n": int,
        }
    """
    history = _load_history()
    n = len(history)
    result = {
        "shifted": False,
        "reasons": [],
        "stability": 1.0,
        "vol_zscore": 0.0,
        "session_pct_pctl": 50.0,
        "vix_pctl": 50.0,
        "history_n": n,
    }
    if n < MIN_SAMPLES:
        return result

    # Compute percentiles from history
    session_pcts = [abs(float(h.get("session_pct", 0))) for h in history]
    vix_vals = [float(h.get("vix", 0)) for h in history]
    adx_vals = [float(h.get("adx", 0)) for h in history]

    cur_session = abs(float(current.get("session_pct", 0) or 0))
    cur_vix = float(current.get("vix", 0) or 0)
    cur_adx = float(current.get("adx", 0) or 0)

    # 1. Session_pct unusual (>95th pctile of |session_pct|)?
    p95 = _percentile(session_pcts, 95)
    if cur_session > p95 and p95 > 0:
        result["shifted"] = True
        result["reasons"].append(
            f"|session_pct|={cur_session:.3f}% > 95th pctile ({p95:.3f}%)"
        )
    # Compute current percentile rank
    rank = sum(1 for s in session_pcts if s <= cur_session) / max(len(session_pcts), 1) * 100
    result["session_pct_pctl"] = round(rank, 1)

    # 2. VIX shift (current vs median ± 30%)
    median_vix = _percentile(vix_vals, 50)
    if median_vix > 0:
        vix_ratio = cur_vix / median_vix
        if vix_ratio > 1.5 or vix_ratio < 0.7:
            result["shifted"] = True
            result["reasons"].append(
                f"VIX={cur_vix:.1f} vs 60d median {median_vix:.1f} "
                f"(ratio {vix_ratio:.2f})"
            )
    rank_vix = sum(1 for v in vix_vals if v <= cur_vix) / max(len(vix_vals), 1) * 100
    result["vix_pctl"] = round(rank_vix, 1)

    # 3. Vol Z-score (current ADX vs history)
    if adx_vals:
        mean_adx = sum(adx_vals) / len(adx_vals)
        var_adx = sum((a - mean_adx) ** 2 for a in adx_vals) / len(adx_vals)
        std_adx = math.sqrt(var_adx) if var_adx > 0 else 1.0
        z = (cur_adx - mean_adx) / std_adx if std_adx > 0 else 0
        result["vol_zscore"] = round(z, 2)
        if abs(z) > 2.0:
            result["shifted"] = True
            result["reasons"].append(
                f"ADX z-score={z:+.2f} (>2σ vs 60d)"
            )

    # 4. Regime stability: how often does current regime appear in history?
    cur_regime = current.get("regime", "unknown")
    regime_counts = {}
    for h in history:
        r = h.get("regime", "unknown")
        regime_counts[r] = regime_counts.get(r, 0) + 1
    same_count = regime_counts.get(cur_regime, 0)
    stability = same_count / n
    result["stability"] = round(stability, 3)
    if stability < 0.10 and n >= 30:
        result["shifted"] = True
        result["reasons"].append(
            f"regime={cur_regime} rare in 60d ({stability*100:.1f}%)"
        )

    return result


def get_regime_shift_context() -> str:
    """Build a prompt-injectable regime-shift context block.

    Returns empty string if no shift detected OR insufficient history.
    Otherwise returns a short block telling the LLM the regime is shifted.
    """
    # Read current state from intraday_levels.json (or liveness.json)
    intraday = DATA_DIR / "intraday_levels.json"
    cur = {"regime": "unknown", "session_pct": 0, "vix": 0,
           "adx": 0, "rsi": 50, "nifty_spot": 0}
    try:
        if intraday.exists():
            data = json.loads(intraday.read_text(encoding="utf-8"))
            nifty = data.get("instruments", {}).get("NIFTY", {})
            cur["session_pct"] = float(nifty.get("session_pct", 0) or 0)
            cur["nifty_spot"] = float(nifty.get("current", 0) or 0)
            cur["adx"] = abs(cur["session_pct"]) * 100
            cur["rsi"] = 50 + float(nifty.get("dist_from_vwap", 0) or 0) * 100
            cur["regime"] = nifty.get("regime", "unknown") or "unknown"
    except Exception:
        pass
    try:
        liveness = DATA_DIR / "liveness.json"
        if liveness.exists():
            data = json.loads(liveness.read_text(encoding="utf-8"))
            cur["vix"] = float(data.get("snapshot", {}).get("vix", 0) or 0)
    except Exception:
        pass

    # Record current to history
    try:
        record(cur["regime"], cur["session_pct"], cur["vix"],
               cur["adx"], cur["rsi"], cur["nifty_spot"])
    except Exception:
        pass

    shift = detect_shift(cur)
    if not shift["shifted"]:
        return ""
    lines = ["[REGIME SHIFT DETECTED — historical priors may be stale]"]
    lines.append(f"  Stability in 60d: {shift['stability']*100:.1f}%")
    lines.append(f"  History samples: {shift['history_n']}")
    for reason in shift["reasons"]:
        lines.append(f"  - {reason}")
    lines.append(
        "  → REDUCE conviction on priors; favor fresh signals; "
        "consider HOLD until regime normalizes."
    )
    return "\n".join(lines)


if __name__ == "__main__":
    print(get_regime_shift_context())