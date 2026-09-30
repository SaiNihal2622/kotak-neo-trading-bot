"""Cleanup script: reject any PROPOSED order older than 1 hour.

PHASE 6 FIX 2026-09-30: 634 legacy orders from the broken-condor era
accumulated in the order book with status=PROPOSED. They never filled
because the broker path was disabled in DRY-RUN mode. This script marks
them REJECTED so they stop cluttering /api/state and dashboard views.

Usage:
    .venv\Scripts\python.exe scripts\cleanup_stuck_orders.py [--dry-run]
    .venv\Scripts\python.exe scripts\cleanup_stuck_orders.py --max-age-min 5

Safe to run any number of times — only touches PROPOSED orders.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone as tz_ist
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data_cache" / "state.db"

IST = tz_ist(timedelta(hours=5, minutes=30))


def _parse_opened_at(opened_at: str) -> datetime | None:
    """Parse the order's opened_at field — multiple shapes seen in the wild."""
    if not opened_at:
        return None
    try:
        # ISO 8601 — handle 'Z' suffix too
        s = opened_at.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        return dt.astimezone(IST)
    except Exception:
        return None


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="only count, don't write")
    p.add_argument("--max-age-min", type=int, default=60,
                   help="reject PROPOSED orders older than N minutes (default 60)")
    args = p.parse_args()

    if not DB_PATH.exists():
        print(f"[cleanup] {DB_PATH} not found — nothing to do")
        return 0

    now_ist = datetime.now(IST)
    cutoff = now_ist - timedelta(minutes=args.max_age_min)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Inspect the schema — orders table may be 'orders' or 'open_orders' or similar
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row["name"] for row in cur.fetchall()}
    if "orders" not in tables:
        print(f"[cleanup] no 'orders' table; tables={tables}")
        return 0

    cur.execute("SELECT name FROM pragma_table_info('orders')")
    cols = {row["name"] for row in cur.fetchall()}
    if "status" not in cols or "order_id" not in cols:
        print(f"[cleanup] 'orders' missing status/order_id cols; cols={cols}")
        return 0

    cur.execute("SELECT order_id, status, opened_at, ts, tag FROM orders WHERE status='PROPOSED'")
    proposed = [dict(r) for r in cur.fetchall()]

    to_reject: list[dict] = []
    no_ts: list[dict] = []
    for o in proposed:
        opened = _parse_opened_at(o.get("opened_at") or "") or _parse_opened_at(o.get("ts") or "")
        if opened is None:
            no_ts.append(o)
            continue
        if opened < cutoff:
            to_reject.append({**o, "_opened_at": opened.isoformat()})

    print(f"[cleanup] PROPOSED total: {len(proposed)}")
    print(f"[cleanup] no-timestamp (will leave): {len(no_ts)}")
    print(f"[cleanup] older than {args.max_age_min}m ({cutoff.strftime('%H:%M:%S')} IST): {len(to_reject)}")

    # Tag breakdown for transparency
    by_tag: dict[str, int] = {}
    for o in to_reject:
        t = o.get("tag") or "<no tag>"
        by_tag[t] = by_tag.get(t, 0) + 1
    print("[cleanup] by tag:")
    for tag, count in sorted(by_tag.items(), key=lambda x: -x[1]):
        print(f"    {tag}: {count}")

    if args.dry_run:
        print("[cleanup] DRY-RUN — no writes")
        return 0

    if not to_reject:
        print("[cleanup] nothing to do")
        return 0

    # Mark them REJECTED + record reason
    reject_ids = [o["order_id"] for o in to_reject]
    placeholders = ",".join("?" for _ in reject_ids)
    cur.execute(
        f"UPDATE orders SET status='REJECTED' WHERE order_id IN ({placeholders}) AND status='PROPOSED'",
        reject_ids,
    )
    affected = cur.rowcount
    conn.commit()
    conn.close()

    print(f"[cleanup] marked REJECTED: {affected}")

    # Write a journal entry so the dashboard can show this happened
    journal_path = PROJECT_ROOT / "data_cache" / "trade_journal.jsonl"
    try:
        entry = {
            "ts": now_ist.isoformat(),
            "event": "stuck_order_cleanup",
            "rejected_count": affected,
            "max_age_min": args.max_age_min,
            "by_tag": by_tag,
        }
        with open(journal_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        print(f"[cleanup] journal entry written to {journal_path.name}")
    except Exception as e:
        print(f"[cleanup] journal write failed (non-blocking): {e}")

    return 0


if __name__ == "__main__":
    sys.exit(main())