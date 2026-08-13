"""One-shot script: reconcile trades_state.json with paper_state.json.

Day 3/4 incident: 4 iron condors (16 legs) filled in paper_state.json positions
after EOD, but trades_state.json had them marked as closed_at=EOD with orders
still in status=open + avg_fill_price=0. This script:

  1. Reads paper_state.json positions (broker is source of truth for open positions)
  2. For each broker position, finds the matching order in trades_state.json
     and updates it to status=complete with the broker's avg_price
  3. If ALL orders in a trade are now complete but the trade was marked
     closed (EOD), reopens the trade (closed_at = None, status = "open")
     because the broker still shows the position
  4. Writes the new top-level derived fields (status, underlying, leg_count, pnl)
  5. Saves atomically

Run as:  python -m scripts.sync_trades_state
or:      .venv/Scripts/python.exe scripts/sync_trades_state.py
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Force UTF-8 stdout on Windows
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PAPER_PATH = PROJECT_ROOT / "data_cache" / "paper_state.json"
TRADES_PATH = PROJECT_ROOT / "data_cache" / "trades_state.json"


def main() -> int:
    if not PAPER_PATH.exists():
        print(f"❌ {PAPER_PATH} not found", file=sys.stderr)
        return 1
    if not TRADES_PATH.exists():
        print(f"❌ {TRADES_PATH} not found", file=sys.stderr)
        return 1

    paper = json.loads(PAPER_PATH.read_text(encoding="utf-8"))
    broker_positions = paper.get("positions", {})  # {symbol: {qty, avg_price, ...}}

    trades_state = json.loads(TRADES_PATH.read_text(encoding="utf-8"))
    trades = trades_state.get("trades", {})

    orders_updated = 0
    orders_unmatched = 0
    trades_reopened = 0
    trades_pnl_updated = 0

    for tid, t in trades.items():
        plan_underlying = (t.get("plan") or {}).get("underlying", "")
        all_orders_complete = True
        any_order_open = False
        for o in t.get("orders", []):
            sym = o.get("symbol", "")
            broker = broker_positions.get(sym)
            if broker and o.get("status") != "complete" and o.get("avg_fill_price", 0) <= 0:
                # Update order from broker data
                o["avg_fill_price"] = float(broker.get("avg_price", 0) or 0)
                o["status"] = "complete"
                o["filled_qty"] = o.get("qty", 0)
                orders_updated += 1
            elif not broker and o.get("status") == "open":
                # Order is open in our system but no broker position
                # Don't force-close; just track for analysis
                any_order_open = True
                all_orders_complete = False
                orders_unmatched += 1
            # Check if all orders are now complete
            if o.get("status") != "complete":
                all_orders_complete = False
            if o.get("status") == "open":
                any_order_open = True

        # Trade-level reconciliation
        # Scenario 1: Trade was marked closed (EOD) but broker has all legs
        #   → reopen the trade (status=open, closed_at=None)
        if t.get("closed_at") and all_orders_complete:
            # All orders filled in broker; trade shouldn't be closed
            old_closed = t["closed_at"]
            t["closed_at"] = None
            t["exit_reason"] = ""
            t["status"] = "open"
            trades_reopened += 1
            print(f"  REOPEN {tid} ({plan_underlying}, {t.get('leg_count', len(t.get('orders', [])))} legs) — was closed at {old_closed}")

        # Compute current P&L (realized; live unrealized is 0 for paper since
        # we don't track mark-to-market here — that's a separate module)
        # The 4 ICs received credit = sum of (SELL fills - BUY fills).
        # In our schema, realized_pnl is the P&L when the trade was closed.
        # For open trades, we compute unrealized based on current LTPs.
        if t.get("status") == "open" and t.get("closed_at") is None:
            unrealized = 0.0
            for o in t.get("orders", []):
                sym = o.get("symbol", "")
                bp = broker_positions.get(sym)
                if not bp:
                    continue
                fill = float(o.get("avg_fill_price", 0) or 0)
                ltp = float(bp.get("ltp", 0) or 0)
                if fill <= 0 or ltp <= 0:
                    continue
                qty = int(o.get("qty", 0) or 0)
                # SELL = positive P&L when LTP < fill; BUY = positive when LTP > fill
                side = o.get("side", "BUY")
                sign = -1 if side == "SELL" else 1
                unrealized += sign * (ltp - fill) * qty
            t["pnl"] = round(unrealized, 2)
            trades_pnl_updated += 1

        # Populate derived fields
        t["status"] = "closed" if t.get("closed_at") else "open"
        t["underlying"] = plan_underlying
        t["leg_count"] = len(t.get("orders", []))
        t["entry_time"] = t.get("opened_at")

    # Write back
    tmp = TRADES_PATH.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(trades_state, indent=2, default=str, ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(tmp, TRADES_PATH)

    print(f"\n✅ {TRADES_PATH} updated")
    print(f"   orders updated:         {orders_updated}")
    print(f"   orders still open:      {orders_unmatched}")
    print(f"   trades reopened:        {trades_reopened}")
    print(f"   open trades P&L recomputed: {trades_pnl_updated}")

    # Show summary
    open_count = sum(1 for t in trades.values() if t.get("status") == "open")
    closed_count = sum(1 for t in trades.values() if t.get("status") == "closed")
    total_open_pnl = sum(t.get("pnl", 0) for t in trades.values() if t.get("status") == "open")
    print(f"\n   open trades:   {open_count} (unrealized P&L: ₹{total_open_pnl:,.2f})")
    print(f"   closed trades: {closed_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
