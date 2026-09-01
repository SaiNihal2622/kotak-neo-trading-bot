"""oi_change_detector.py — real-time OI build-up / unwinding detector.

Open interest (OI) changes reveal institutional positioning BEFORE the move:

  - BUILD-UP (OI ↑): writers are selling premium at a strike = new support/resistance.
    Heavy CE build-up above spot = call writers expect the rally to stall.
    Heavy PE build-up below spot = put writers expect the dip to hold.

  - UNWINDING (OI ↓): writers are closing positions = prior S/R breaking down.
    Sudden PE unwinding below spot = put wall collapsing, expect more downside.

  - PCR SHIFT: put-call ratio change = institutional sentiment shift.

This module:
  1. Pulls current OI from `KotakProdFeed.get_oi_map()` every N seconds
  2. Persists snapshots to `data_cache/oi_snapshots/{symbol}_{ts}.json`
  3. Compares current to N-minutes-ago snapshot
  4. Surfaces "significant" changes (>5% OI shift or >20% absolute)
  5. Exposes to LLM via `get_oi_changes_for_llm(symbol, lookback_min=15)`

Wired into quant_service event loop. Alerts via Telegram when large moves
(>15% OI shift) detected.

Usage:
    from oi_change_detector import get_oi_changes_for_llm
    changes = get_oi_changes_for_llm("NIFTY", lookback_min=15)
    # Returns: {"n_changes": N, "build_up": [...], "unwinding": [...], "pcr_shift": ...}
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
DATA = ROOT / 'data_cache'
SNAPSHOTS = DATA / 'oi_snapshots'
SNAPSHOTS.mkdir(parents=True, exist_ok=True)
OI_LOG = DATA / 'oi_changes.jsonl'
sys.path.insert(0, str(ROOT / "scripts"))


# ---------------------------------------------------------------------------
# Snapshotting
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _safe_float(x, default=0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _safe_int(x, default=0) -> int:
    try:
        return int(x)
    except (TypeError, ValueError):
        return default


def capture_snapshot(underlying: str) -> Optional[dict]:
    """Pull current OI map from KotakProdFeed and save to disk.

    Returns: the snapshot dict {strike: {ce_oi, pe_oi, ce_ltp, pe_ltp}, spot, ts}
    """
    try:
        # Lazy import to avoid hard dependency on broker being up
        sys.path.insert(0, str(ROOT))
        from kotak_bot.data.kotak_prod_feed import KotakProdFeed
        feed = KotakProdFeed.instance() if hasattr(KotakProdFeed, "instance") else KotakProdFeed()
    except Exception as e:
        return {"error": f"feed_unavailable: {str(e)[:100]}"}

    try:
        oi_map = feed.get_oi_map(underlying)
    except Exception as e:
        return {"error": f"oi_fetch_failed: {str(e)[:100]}"}

    if not oi_map:
        return {"error": "empty_oi_map"}

    # Get spot from liveness
    try:
        live = json.loads((DATA / "liveness.json").read_text(encoding="utf-8"))
        spot = _safe_float(live.get("snapshot", {}).get("spot"))
    except Exception:
        spot = 0.0

    snap = {
        "ts": _now_iso(),
        "underlying": underlying,
        "spot": spot,
        "strikes": oi_map,
    }

    # Save
    fname = f"{underlying}_{int(time.time())}.json"
    try:
        (SNAPSHOTS / fname).write_text(json.dumps(snap, default=str), encoding="utf-8")
    except Exception:
        pass

    # Cleanup snapshots older than 24h
    try:
        cutoff_ts = int(time.time()) - 86400
        for p in SNAPSHOTS.glob(f"{underlying}_*.json"):
            try:
                ts = int(p.stem.split("_")[-1])
                if ts < cutoff_ts:
                    p.unlink()
            except Exception:
                continue
    except Exception:
        pass

    return snap


def get_oi_snapshot_at(underlying: str, lookback_min: int) -> Optional[dict]:
    """Find the most recent snapshot for `underlying` at least `lookback_min` ago.

    Returns: snapshot dict or None if no qualifying snapshot.
    """
    target_ts = time.time() - (lookback_min * 60)
    candidates = []
    for p in SNAPSHOTS.glob(f"{underlying}_*.json"):
        try:
            ts = int(p.stem.split("_")[-1])
            if ts <= target_ts:
                candidates.append((ts, p))
        except Exception:
            continue
    if not candidates:
        return None
    # Pick the most recent one that is at or before target_ts (closest to target)
    candidates.sort(key=lambda x: abs(x[0] - target_ts))
    _, path = candidates[0]
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Change detection
# ---------------------------------------------------------------------------

def compute_changes(prev: dict, cur: dict) -> dict:
    """Compare two OI snapshots. Return build-up / unwinding / PCR shift.

    Args:
        prev, cur: snapshot dicts with `strikes: {strike: {ce_oi, pe_oi, ...}}`

    Returns: {build_up: [...], unwinding: [...], pcr_change: float, pcr_now: float, pcr_prev: float}
    """
    prev_strikes = prev.get("strikes", {}) or {}
    cur_strikes = cur.get("strikes", {}) or {}

    all_strikes = set(prev_strikes.keys()) | set(cur_strikes.keys())
    build_up = []
    unwinding = []

    total_pe_oi_prev = 0
    total_ce_oi_prev = 0
    total_pe_oi_cur = 0
    total_ce_oi_cur = 0

    for strike in sorted(all_strikes):
        p = prev_strikes.get(strike, {})
        c = cur_strikes.get(strike, {})

        for opt in ("ce", "pe"):
            prev_oi = _safe_int(p.get(f"{opt}_oi"))
            cur_oi = _safe_int(c.get(f"{opt}_oi"))
            if prev_oi == 0 and cur_oi == 0:
                continue

            if opt == "pe":
                total_pe_oi_prev += prev_oi
                total_pe_oi_cur += cur_oi
            else:
                total_ce_oi_prev += prev_oi
                total_ce_oi_cur += cur_oi

            if prev_oi == 0 and cur_oi > 0:
                # New OI
                change_pct = 100.0
            elif prev_oi > 0:
                change_pct = ((cur_oi - prev_oi) / prev_oi) * 100
            else:
                continue

            if change_pct >= 5.0:  # build-up threshold
                build_up.append({
                    "strike": strike,
                    "opt_type": opt.upper(),
                    "prev_oi": prev_oi,
                    "cur_oi": cur_oi,
                    "change_pct": round(change_pct, 1),
                    "ltp": _safe_float(c.get(f"{opt}_ltp")),
                })
            elif change_pct <= -5.0:  # unwinding
                unwinding.append({
                    "strike": strike,
                    "opt_type": opt.upper(),
                    "prev_oi": prev_oi,
                    "cur_oi": cur_oi,
                    "change_pct": round(change_pct, 1),
                    "ltp": _safe_float(c.get(f"{opt}_ltp")),
                })

    # PCR shift
    pcr_prev = total_pe_oi_prev / max(1, total_ce_oi_prev)
    pcr_cur = total_pe_oi_cur / max(1, total_ce_oi_cur)
    pcr_change = pcr_cur - pcr_prev

    return {
        "build_up": build_up,
        "unwinding": unwinding,
        "pcr_prev": round(pcr_prev, 3),
        "pcr_now": round(pcr_cur, 3),
        "pcr_change": round(pcr_change, 3),
        "total_pe_oi_prev": total_pe_oi_prev,
        "total_ce_oi_prev": total_ce_oi_prev,
        "total_pe_oi_cur": total_pe_oi_cur,
        "total_ce_oi_cur": total_ce_oi_cur,
    }


def detect_significant_changes(underlying: str, lookback_min: int = 15,
                                 build_up_pct: float = 5.0,
                                 unwinding_pct: float = -5.0) -> dict:
    """Capture current snapshot, compare to N-minutes-ago snapshot.

    Returns: {n_changes, build_up: [...], unwinding: [...], pcr_change, ...}
    """
    cur = capture_snapshot(underlying)
    if not cur or "error" in cur:
        return {"underlying": underlying, "error": cur.get("error") if cur else "no_snapshot",
                "n_changes": 0, "build_up": [], "unwinding": []}

    prev = get_oi_snapshot_at(underlying, lookback_min)
    if not prev:
        # No baseline yet — record current as baseline, return empty
        return {"underlying": underlying, "n_changes": 0, "build_up": [], "unwinding": [],
                "info": "no_baseline_yet", "current_spot": cur.get("spot"),
                "current_ts": cur.get("ts")}

    changes = compute_changes(prev, cur)

    # Filter to significant only
    sig_build = [b for b in changes["build_up"] if b["change_pct"] >= build_up_pct]
    sig_unwind = [u for u in changes["unwinding"] if u["change_pct"] <= unwinding_pct]

    out = {
        "underlying": underlying,
        "ts_current": cur.get("ts"),
        "ts_baseline": prev.get("ts"),
        "lookback_min": lookback_min,
        "current_spot": cur.get("spot"),
        "n_changes": len(sig_build) + len(sig_unwind),
        "build_up": sig_build[:10],  # cap at 10
        "unwinding": sig_unwind[:10],
        "pcr_change": changes["pcr_change"],
        "pcr_now": changes["pcr_now"],
        "pcr_prev": changes["pcr_prev"],
    }

    # Log to JSONL
    try:
        with open(OI_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(out, default=str) + "\n")
    except Exception:
        pass

    return out


# ---------------------------------------------------------------------------
# LLM interface
# ---------------------------------------------------------------------------

def get_oi_changes_for_llm(underlying: str = "NIFTY", lookback_min: int = 15) -> dict:
    """Compact dict for LLM context. Always safe to call.

    Returns: {n_changes, top_build_up: [...3], top_unwinding: [...3], pcr_now, pcr_change, hint}
    """
    try:
        ch = detect_significant_changes(underlying, lookback_min=lookback_min)
    except Exception as e:
        return {"underlying": underlying, "error": str(e)[:100], "n_changes": 0}

    if "error" in ch or "info" in ch:
        return {"underlying": underlying, "n_changes": 0, "hint": "oi_baseline_building",
                "info": ch.get("info") or ch.get("error")}

    # Compact: top 3 build-up + top 3 unwinding
    top_bu = sorted(ch["build_up"], key=lambda x: -x["change_pct"])[:3]
    top_uw = sorted(ch["unwinding"], key=lambda x: x["change_pct"])[:3]

    # Hint
    pcr = ch["pcr_change"]
    if pcr > 0.1:
        bias = "bullish (more puts being written = support)"
    elif pcr < -0.1:
        bias = "bearish (call writers stepping back)"
    else:
        bias = "neutral"

    return {
        "underlying": underlying,
        "ts_current": ch.get("ts_current"),
        "lookback_min": lookback_min,
        "n_changes": ch["n_changes"],
        "top_build_up": [{"strike": b["strike"], "side": b["opt_type"],
                          "change_pct": b["change_pct"], "oi_now": b["cur_oi"]} for b in top_bu],
        "top_unwinding": [{"strike": u["strike"], "side": u["opt_type"],
                           "change_pct": u["change_pct"], "oi_now": u["cur_oi"]} for u in top_uw],
        "pcr_now": ch["pcr_now"],
        "pcr_change": ch["pcr_change"],
        "bias": bias,
        "hint": f"{ch['n_changes']} sig OI changes; PCR {ch['pcr_prev']}→{ch['pcr_now']} ({bias})",
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--underlying", default="NIFTY")
    p.add_argument("--lookback", type=int, default=15)
    p.add_argument("--capture", action="store_true", help="Only capture snapshot, don't analyze")
    args = p.parse_args()

    if args.capture:
        s = capture_snapshot(args.underlying)
        print(json.dumps(s, indent=2, default=str)[:500])
    else:
        print(json.dumps(get_oi_changes_for_llm(args.underlying, args.lookback), indent=2, default=str))
