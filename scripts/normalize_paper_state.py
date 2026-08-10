"""Normalize paper_state.json in place.

After the SELL bug + close race, paper_state.json may contain:
- Phantom LONG positions (from EOD close-buys against lost shorts)
- Naked SHORT positions (from incomplete EOD square-off, e.g. when order_mgr
  lost its _trades dict on restart)
- Open SELL/BUY orders that were meant to close those phantoms (now stuck, no ticks)

This script:
1. Wipes the 4 known phantom LONG positions
2. Wipes any SHORT positions (naked shorts are always a bug post-fix)
3. Marks orphan_close + startup_reconcile orders as CANCELLED
4. Saves the cleaned state

Idempotent — safe to run multiple times.

USE WITH CAUTION: only run when the bot is STOPPED to avoid races.
"""
import json
import sys
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
state_path = ROOT / "data_cache" / "paper_state.json"

# known phantoms (the 4 LONGs created by the SELL bug at 15:15 EOD)
PHANTOM_SYMBOLS = {
    "NIFTY10AUG2624600CE",
    "NIFTY10AUG2624400PE",
    "BANKNIFTY10AUG2652000CE",
    "BANKNIFTY10AUG2652000PE",
}

state = json.loads(state_path.read_text(encoding="utf-8"))
print(f"Loaded state: cash=Rs.{state['cash']:,.0f}  realized=Rs.{state['realized_pnl']:,.0f}")
print(f"  orders: {len(state['orders'])}")
print(f"  positions: {len(state['positions'])}")

# 1) drop phantoms (only LONGs at the known phantom symbols)
removed_positions = 0
for sym in list(state["positions"].keys()):
    p = state["positions"][sym]
    if sym in PHANTOM_SYMBOLS and p.get("qty", 0) > 0:
        print(f"  removing phantom position: {sym} qty={p['qty']}")
        del state["positions"][sym]
        removed_positions += 1
    elif p.get("qty", 0) < 0:
        # Naked SHORTs are always a bug post-fix (EOD didn't square off)
        print(f"  removing naked SHORT: {sym} qty={p['qty']}")
        del state["positions"][sym]
        removed_positions += 1
print(f"  -> removed {removed_positions} positions")

# 2) cancel any orphan orders that are still open
cancelled = 0
for oid, od in state["orders"].items():
    if od.get("status") in ("open", "OPEN", "OrderStatus.OPEN"):
        if od.get("tag") in ("orphan_close", "startup_reconcile", "close_", None):
            print(f"  cancelling open order: {oid} tag={od.get('tag')} symbol={od.get('symbol')}")
            od["status"] = "cancelled"
            cancelled += 1
print(f"  -> cancelled {cancelled} open orders")

# write back atomically
tmp = state_path.with_suffix(".tmp")
tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
import os
os.replace(tmp, state_path)
print(f"\nWrote normalized state to {state_path}")
print(f"  final orders: {len(state['orders'])}")
print(f"  final positions: {len(state['positions'])}")
