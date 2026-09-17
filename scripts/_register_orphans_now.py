"""One-shot: register current broker positions as managed trades immediately.

Useful when the bot is running and the orphan-registration startup hook hasn't
fired yet. Loads paper_client positions and pushes them into order_mgr's
trades dict via the same path the startup hook uses. Saves order_mgr state.

Usage:
    python scripts/_register_orphans_now.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

from kotak_bot.broker.paper_client import PaperClient
from kotak_bot.execution.order_manager import OrderManager

print("=== ORPHAN-RECOVER: one-shot ===")
broker = PaperClient(starting_capital=100000, persist_path="data_cache/paper_state.json")
broker.connect()
broker_pos = broker.get_positions()
print(f"Broker positions: {len(broker_pos)}")
for p in broker_pos:
    print(f"  {p.symbol}: qty={p.qty} avg={p.avg_price} ltp={p.ltp}")

# Init order_mgr (loads existing trades_state.json)
order_mgr = OrderManager(broker)
before_count = len(order_mgr.open_trades())
print(f"\nOrderMgr open trades before: {before_count}")

# Register orphans
n = order_mgr.register_orphan_positions(broker_pos)
after_count = len(order_mgr.open_trades())
print(f"Registered {n} orphans")
print(f"OrderMgr open trades after: {after_count}")

print("\n=== DONE ===")