"""Normalize paper_state.json in place.

After the SELL bug + close race, paper_state.json may contain:
- Phantom LONG positions (from EOD close-buys against lost shorts)
- Open SELL orders that were meant to close those phantoms (now stuck, no ticks)

This script:
1. Wipes the 4 known phantom positions
2. Marks any SELL MARKET orders with tag='orphan_close' as CANCELLED
3. Saves the cleaned state

Idempotent — safe to run multiple times.
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

# 1) drop phantoms
removed_positions = 0
for sym in list(state["positions"].keys()):
    if sym in PHANTOM_SYMBOLS:
        p = state["positions"][sym]
        if p.get("qty", 0) > 0:  # only drop if it's a phantom LONG
            print(f"  removing phantom position: {sym} qty={p['qty']}")
            del state["positions"][sym]
            removed_positions += 1
print(f"  -> removed {removed_positions} phantom positions")

# 2) cancel any orphan_close orders that are still open
cancelled = 0
for oid, od in state["orders"].items():
    if od.get("tag") == "orphan_close" and od.get("status") in ("open", "OPEN", "OrderStatus.OPEN"):
        print(f"  cancelling open order: {oid} {od.get('symbol')} {od.get('side')}")
        od["status"] = "cancelled"
        cancelled += 1
print(f"  -> cancelled {cancelled} orphan orders")

# write back atomically
tmp = state_path.with_suffix(".tmp")
tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
import os
os.replace(tmp, state_path)
print(f"\nWrote normalized state to {state_path}")
print(f"  final orders: {len(state['orders'])}")
print(f"  final positions: {len(state['positions'])}")
