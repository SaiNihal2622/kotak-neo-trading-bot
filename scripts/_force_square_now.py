"""_force_square_now.py - One-shot force-square for paper positions.

Used to clean up when bot's OrderManager lost track of brain-driven trades
(see FIX 2026-09-03 14:38). Reads paper_state.json positions, places
close MARKET orders via the paper client, and reports P&L.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

# Load paper state
ps = json.loads((ROOT / "data_cache" / "paper_state.json").read_text(encoding="utf-8"))
positions = ps.get("positions", {})

if not positions:
    print("No open positions. Nothing to close.")
    sys.exit(0)

# Try to use the bot's paper client for proper close
try:
    from kotak_bot.broker.paper_client import PaperClient
    pc = PaperClient() if hasattr(PaperClient, "from_env") else PaperClient(starting_capital=100000, persist_path="data_cache/paper_state.json")
    pc.connect()  # FIX 2026-09-03 14:50: connect before place_order
except Exception as e:
    print(f"PaperClient init failed: {e}")
    sys.exit(1)

# Place close orders
from kotak_bot.broker.base import Order, OrderSide, OrderType, ProductType

closed = 0
for sym, p in positions.items():
    qty = p.get("qty", 0)
    if qty == 0:
        continue
    # To close, place opposite side
    side = OrderSide.SELL if qty > 0 else OrderSide.BUY
    abs_qty = abs(qty)
    order = Order(
        symbol=sym,
        side=side,
        qty=abs_qty,
        order_type=OrderType.MARKET,
        product=ProductType.MIS,
        price=0.0,
        tag="FORCE-SQUARE-NOW",
    )
    try:
        result = pc.place_order(order)
        if result.status.value in ("complete", "filled", "open"):
            print(f"CLOSED {sym} {side.value} {abs_qty} @ {result.avg_fill_price or 0}")
            closed += 1
        else:
            print(f"FAILED {sym}: {result.rejection_reason}")
    except Exception as e:
        print(f"ERROR {sym}: {e}")

# Show final state
ps2 = json.loads((ROOT / "data_cache" / "paper_state.json").read_text(encoding="utf-8"))
print(f"\n=== AFTER FORCE-SQUARE ===")
print(f"Cash: Rs.{ps2.get('cash', 0):,.2f}")
print(f"Realized P&L: Rs.{ps2.get('realized_pnl', 0):,.2f}")
print(f"Open positions: {len(ps2.get('positions', {}))}")
print(f"Closed {closed} of {len(positions)} positions")
