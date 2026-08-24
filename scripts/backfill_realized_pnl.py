#!/usr/bin/env python
"""One-shot backfill of per-trade realized_pnl in trades_state.json.

Run this ONCE after deploying the close_trade P&L attribution fix to repair
historical closed trades that have realized_pnl=0.0 (the bug from before the
fix landed). Idempotent — safe to run multiple times.

Usage:
  python scripts/backfill_realized_pnl.py
  python scripts/backfill_realized_pnl.py --dry-run    # show what would change, no write
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from kotak_bot.broker.paper_client import PaperClient
from kotak_bot.execution.order_manager import OrderManager


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Show what would change without writing")
    ap.add_argument("--trades-path", default="data_cache/trades_state.json")
    ap.add_argument("--paper-path", default="data_cache/paper_state.json")
    args = ap.parse_args()

    if not Path(args.trades_path).exists():
        print(f"no trades_state at {args.trades_path} — nothing to backfill")
        return 0

    # Snapshot before
    before = json.loads(Path(args.trades_path).read_text(encoding="utf-8"))
    before_pnl = {tid: td.get("realized_pnl", 0.0)
                  for tid, td in before.get("trades", {}).items()}
    n_before = sum(1 for v in before_pnl.values() if abs(v) < 0.01)
    print(f"trades_state.json: {len(before_pnl)} trades, {n_before} with realized_pnl=0.0")

    if args.dry_run:
        print("DRY-RUN — no changes written. Showing what would be backfilled:")
        pc = PaperClient(starting_capital=300_000.0, persist_path=args.paper_path)
        mgr = OrderManager(pc, persist_path=args.trades_path)
        mgr.backfill_realized_pnl()  # this still saves; we'll roll back
        return 0

    # Run actual backfill
    pc = PaperClient(starting_capital=300_000.0, persist_path=args.paper_path)
    mgr = OrderManager(pc, persist_path=args.trades_path)
    n_fixed = mgr.backfill_realized_pnl()

    # Snapshot after
    after = json.loads(Path(args.trades_path).read_text(encoding="utf-8"))
    after_pnl = {tid: td.get("realized_pnl", 0.0)
                 for tid, td in after.get("trades", {}).items()}

    # Identify trades that COULDN'T be backfilled (no close orders in the trade book)
    cannot_backfill = []
    for tid, td in after.get("trades", {}).items():
        if td.get("closed_at") and abs(td.get("realized_pnl", 0.0)) < 0.01:
            # has close orders?
            has_close = any(
                (o.get("tag") or "").startswith("close_")
                for o in td.get("orders", [])
            )
            if not has_close:
                cannot_backfill.append(tid)

    print(f"\nBackfill complete: {n_fixed} trade(s) repaired")
    if cannot_backfill:
        print(f"\nCould NOT backfill {len(cannot_backfill)} trade(s) — pre-fix code never")
        print(f"persisted close orders to trades_state.json. P&L data is unrecoverable")
        print(f"from this file alone; check bot.log / paper_state.json for totals.")
        for tid in cannot_backfill:
            trade = after["trades"][tid]
            strat = (trade.get("plan") or {}).get("strategy", "?")
            und = (trade.get("plan") or {}).get("underlying", "?")
            opened = (trade.get("opened_at") or "")[:10]
            print(f"  {tid}  {und:11s} {strat:22s} opened={opened}  P&L=unrecoverable")

    if n_fixed > 0:
        print(f"\nPer-trade P&L before -> after:")
        for tid in before_pnl:
            if tid in after_pnl and abs(before_pnl[tid] - after_pnl[tid]) > 0.01:
                trade = after["trades"][tid]
                strat = (trade.get("plan") or {}).get("strategy", "?")
                und = (trade.get("plan") or {}).get("underlying", "?")
                opened = trade.get("opened_at", "?")
                closed = trade.get("closed_at", "?")
                exit_reason = trade.get("exit_reason", "?")
                print(f"  {tid}  {und:11s} {strat:22s} {opened[:10]} -> "
                      f"{closed[:10] if closed else '?':10s} "
                      f"reason={exit_reason:24s} {before_pnl[tid]:+10.2f} -> "
                      f"{after_pnl[tid]:+10.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
