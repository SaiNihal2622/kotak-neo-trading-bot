"""Counterfactual tracking — what would have happened if we'd taken the trade.

PHASE 6 FIX 2026-09-30: this is the "learn from missed profits" piece.
For every brain decision, we record:
1. What the brain actually decided (HOLD / OPEN / close)
2. What the counterfactual was (e.g. if HOLD, what would an OPEN have yielded?)
3. The price at decision time and the price N minutes later (or at EOD)

This lets us compute "missed profit" — the gap between what we made
and what we could have made. The brain prompt can then ingest this
data so future decisions improve.

State files:
- data_cache/counterfactual_log.jsonl  (per-decision record)
- data_cache/missed_profit_summary.json (daily aggregates)
- data_cache/lessons_learned.json       (latest aggregated lessons for brain prompt)

Per-record schema:
    {
      "ts": "2026-09-30T13:43:25+05:30",
      "decision": "HOLD" | "OPEN" | "CLOSE",
      "action": {"strategy": "...", "rationale": "..."},
      "counterfactual": {
        "would_have_action": "OPEN" | "CLOSE",
        "would_have_signal_strength": 0.85,
        "would_have_pnl_per_lot": 1500.0,
        "would_have_pnl_at_eod": 1200.0
      },
      "actual_outcome": {
        "pnl_per_lot": 0,
        "pnl_at_eod": 0,
      },
      "missed_pnl_per_lot": 1200.0,
      "missed_pnl_at_eod": 1200.0,
      "regime": "trending_up",
      "vix": 13.6,
      "adx": 37.7
    }

Daily summary schema:
    {
      "date": "2026-09-30",
      "trades_actual": 8,
      "trades_skipped": 5,
      "actual_pnl": 2400.0,
      "missed_pnl": 1200.0,
      "missed_pct": 50.0,
      "lessons": [
        "Skipped 2 high-ADX (>30) longs that would have made +Rs.1800 by EOD",
        "Took 3 mean-reversion shorts in trending regime — all losers — net -Rs.500"
      ]
    }
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data_cache"

IST = timezone(timedelta(hours=5, minutes=30))

CF_LOG = DATA_DIR / "counterfactual_log.jsonl"
DAILY_SUMMARY = DATA_DIR / "missed_profit_summary.json"
LESSONS_FILE = DATA_DIR / "lessons_learned.json"

# Schema for a counterfactual record. We compute these fields:
#   - decision: actual decision made
#   - counterfactual_would_have: what would have happened if we'd taken the alternative
#   - actual_outcome: what actually happened (we may have held the position)
#   - missed_pnl: actual - would_have (positive = we missed a profit)


def _now_ist() -> datetime:
    return datetime.now(IST)


def _read_state_for_core() -> dict:
    """Snapshot of core state — used to compute signal strength and prices."""
    from urllib.request import urlopen
    import json as _j

    core = os.environ.get("KOTAK_CORE_URL", "http://127.0.0.1:8510")
    try:
        with urlopen(f"{core}/api/state", timeout=3) as r:
            return _j.loads(r.read())
    except Exception:
        return {}


def record_decision(
    *,
    decision: str,  # "OPEN" | "HOLD" | "CLOSE"
    action: dict,
    regime: str,
    vix: float,
    adx: float,
    signal_strength: float = 0.0,
    would_have_action: Optional[str] = None,
    would_have_pnl_per_lot: float = 0.0,
) -> None:
    """Append a counterfactual record. Called by brain daemon after each cycle.

    Args:
        decision: what the brain decided (OPEN / HOLD / CLOSE).
        action: the full action dict (rationale, strategy, etc.).
        regime: current market regime (trending_up, range_bound, etc.).
        vix: current India VIX.
        adx: current ADX value (proxy from session_pct).
        signal_strength: 0..1 strength of the signal (how strongly indicators support a trade).
        would_have_action: what the alternative decision was (None if N/A).
        would_have_pnl_per_lot: estimated P&L per lot if alternative was taken.
            Positive = would have profited; negative = would have lost.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Actual P&L so far (filled orders since the decision)
    actual_pnl = 0.0
    # If the brain decided OPEN, the position's current P&L IS the actual outcome.
    # If HOLD, we record 0 actual_pnl since no trade was placed.
    if decision == "OPEN":
        # Will be updated later via update_outcome() once the position closes
        pass

    record = {
        "ts": _now_ist().isoformat(),
        "decision": decision,
        "action": {
            "strategy": action.get("strategy", ""),
            "rationale": (action.get("rationale") or "")[:300],
        },
        "counterfactual": {
            "would_have_action": would_have_action,
            "would_have_signal_strength": signal_strength,
            "would_have_pnl_per_lot": would_have_pnl_per_lot,
        },
        "actual_outcome": {
            "pnl_per_lot": actual_pnl,
        },
        "missed_pnl_per_lot": (
            (would_have_pnl_per_lot - actual_pnl) if decision != "OPEN" else 0.0
        ),
        "regime": regime,
        "vix": vix,
        "adx": adx,
    }
    try:
        with open(CF_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception as e:
        print(f"[counterfactual] write failed: {e}", file=sys.stderr)


def update_outcome(*, ts_match: str, pnl_per_lot: float) -> None:
    """Update an existing record's actual_outcome.pnl_per_lot.

    Called when a position closes (or after EOD) so missed_pnl can be
    finalized. ts_match is the ISO timestamp of the original decision.
    """
    if not CF_LOG.exists():
        return
    try:
        records = []
        updated = False
        with open(CF_LOG, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                rec = json.loads(line)
                if (
                    not updated
                    and rec.get("ts") == ts_match
                    and rec.get("decision") == "OPEN"
                ):
                    rec["actual_outcome"]["pnl_per_lot"] = pnl_per_lot
                    # missed_pnl for OPENs is N/A (we DID trade)
                    rec["missed_pnl_per_lot"] = 0.0
                    updated = True
                records.append(rec)
        if updated:
            with open(CF_LOG, "w", encoding="utf-8") as f:
                for rec in records:
                    f.write(json.dumps(rec) + "\n")
    except Exception as e:
        print(f"[counterfactual] update failed: {e}", file=sys.stderr)


def compute_daily_summary(target_date: Optional[str] = None) -> dict:
    """Aggregate today's counterfactual records into a summary.

    Args:
        target_date: YYYY-MM-DD; default = today IST.
    """
    if target_date is None:
        target_date = _now_ist().strftime("%Y-%m-%d")
    if not CF_LOG.exists():
        return {"date": target_date, "trades_actual": 0, "trades_skipped": 0,
                "actual_pnl": 0.0, "missed_pnl": 0.0, "lessons": []}

    actual_pnl = 0.0
    missed_pnl = 0.0
    trades_actual = 0
    trades_skipped = 0
    skipped_high_strength = 0
    skipped_high_strength_pnl = 0.0

    with open(CF_LOG, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if not rec.get("ts", "").startswith(target_date):
                continue
            decision = rec.get("decision")
            if decision == "OPEN":
                trades_actual += 1
                actual_pnl += float(rec.get("actual_outcome", {}).get("pnl_per_lot", 0))
            elif decision == "HOLD":
                cf = rec.get("counterfactual", {})
                wh = cf.get("would_have_action")
                if wh and wh != "HOLD":
                    trades_skipped += 1
                    missed_pnl += float(rec.get("missed_pnl_per_lot", 0))
                    if float(cf.get("would_have_signal_strength", 0)) >= 0.6:
                        skipped_high_strength += 1
                        skipped_high_strength_pnl += float(rec.get("missed_pnl_per_lot", 0))

    # Build lessons
    lessons = []
    if skipped_high_strength > 0:
        lessons.append(
            f"Skipped {skipped_high_strength} high-strength signals "
            f"(strength≥0.6) that would have netted Rs.{skipped_high_strength_pnl:+.0f}"
        )
    if trades_actual > 0 and actual_pnl < 0:
        lessons.append(
            f"Today's {trades_actual} actual trades net Rs.{actual_pnl:+.0f} — "
            "consider tightening entry conditions"
        )
    if missed_pnl > 1000:
        lessons.append(
            f"Missed profit Rs.{missed_pnl:+.0f} on {trades_skipped} skipped trades — "
            "regime filter may be too strict"
        )

    summary = {
        "date": target_date,
        "trades_actual": trades_actual,
        "trades_skipped": trades_skipped,
        "skipped_high_strength": skipped_high_strength,
        "actual_pnl": round(actual_pnl, 2),
        "missed_pnl": round(missed_pnl, 2),
        "missed_pct": round(100 * missed_pnl / max(1, abs(actual_pnl) + abs(missed_pnl)), 1),
        "lessons": lessons,
    }

    # Save the summary
    try:
        # Merge with existing summaries if file present
        existing = {}
        if DAILY_SUMMARY.exists():
            try:
                existing = json.loads(DAILY_SUMMARY.read_text(encoding="utf-8"))
            except Exception:
                existing = {}
        if not isinstance(existing, dict):
            existing = {}
        existing[target_date] = summary
        # Keep only last 30 days
        sorted_dates = sorted(existing.keys(), reverse=True)[:30]
        existing = {d: existing[d] for d in sorted_dates}
        with open(DAILY_SUMMARY, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[counterfactual] summary write failed: {e}", file=sys.stderr)

    return summary


def get_lessons_for_prompt(max_lessons: int = 5) -> str:
    """Build a short lessons-learned block for the brain prompt.

    Aggregates the last 5 days of missed-profit summaries and surfaces
    the top lessons in <200 chars. Used by brain_daemon when building
    its prompt.
    """
    if not DAILY_SUMMARY.exists():
        return ""
    try:
        data = json.loads(DAILY_SUMMARY.read_text(encoding="utf-8"))
    except Exception:
        return ""
    if not isinstance(data, dict):
        return ""

    # Collect all lessons from the last 5 days, dedupe
    seen = set()
    all_lessons = []
    for d in sorted(data.keys(), reverse=True)[:5]:
        for lesson in data[d].get("lessons", []):
            if lesson not in seen:
                seen.add(lesson)
                all_lessons.append((d, lesson))
        if len(all_lessons) >= max_lessons:
            break

    if not all_lessons:
        return ""

    lines = ["RECENT LESSONS (from past days' counterfactual):"]
    for d, lesson in all_lessons[:max_lessons]:
        lines.append(f"- [{d}] {lesson}")
    return "\n".join(lines)


if __name__ == "__main__":
    # CLI: compute today's summary, optionally print lessons
    p = sys.argv[1] if len(sys.argv) > 1 else None
    if p == "summary":
        s = compute_daily_summary()
        print(json.dumps(s, indent=2))
    elif p == "lessons":
        print(get_lessons_for_prompt())
    else:
        print(__doc__)