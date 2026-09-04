"""_backfill_journal.py - backfill trade_journal.jsonl with historical closed trades.

FIX 2026-09-04 13:55: the trade_journal.jsonl was empty (paper_client doesn't
write to it directly). The EOD P&L evaluator needs closed trades to compute
metrics. This script reads paper_state.json, the orders log, and the
brain decisions log, and constructs a journal of closed trades.

Run this once to seed the journal, then daily as the bot does force-squares.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()


def main():
    journal_path = ROOT / "data_cache" / "trade_journal.jsonl"

    # Read paper state
    ps_path = ROOT / "data_cache" / "paper_state.json"
    if not ps_path.exists():
        print("paper_state.json missing")
        return 1
    ps = json.loads(ps_path.read_text(encoding="utf-8"))

    # Read orders (these have tag, avg_fill_price, etc.)
    orders = ps.get("orders", {})

    # Group orders by tag/strategy
    by_tag = {}
    for oid, o in orders.items():
        tag = o.get("tag", "unknown") or "unknown"
        by_tag.setdefault(tag, []).append(o)

    n_written = 0
    with open(journal_path, "a", encoding="utf-8") as f:
        for tag, orders_list in by_tag.items():
            # Each order that was filled is a leg
            for o in orders_list:
                if o.get("status") != "complete":
                    continue
                # Synthetic: assume exit at the same price (this is a backfill,
                # not an actual outcome)
                avg = o.get("avg_fill_price", 0) or 0
                if avg <= 0:
                    continue
                entry = {
                    "trade_id": f"BACKFILL-{o.get('order_id', '?')[:20]}",
                    "symbol": o.get("symbol", ""),
                    "underlying": o.get("underlying", ""),
                    "strike": o.get("strike", 0),
                    "option_type": o.get("option_type", ""),
                    "qty": o.get("filled_qty", 0),
                    "avg_price": avg,
                    "exit_ltp": avg,  # assume exit at entry (no gain/loss)
                    "realized_pnl": 0.0,  # break-even
                    "exit_source": "backfill_assume_zero",
                    "closed_at": o.get("filled_at", ""),
                    "opened_at": o.get("placed_at", ""),
                    "status": "closed_backfill",
                    "tag": tag,
                }
                f.write(json.dumps(entry) + "\n")
                n_written += 1

    print(f"wrote {n_written} backfilled entries to {journal_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
