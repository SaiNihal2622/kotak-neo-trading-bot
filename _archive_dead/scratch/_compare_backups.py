"""Compare paper_state backups to find when the reset happened."""
import json

paths = [
    "data_cache/backups/20260915_230001/paper_state.json",
    "data_cache/backups/20260916_230001/paper_state.json",
    "data_cache/backups/20260917_230001/paper_state.json",
    "data_cache/paper_state.json",
]

for path in paths:
    try:
        s = json.load(open(path))
        cash = s.get("cash", 0)
        realized = s.get("realized_pnl", 0)
        orders_n = len(s.get("orders", {}))
        positions_n = len(s.get("positions", {}))
        print(f"{path}")
        print(f"  cash: Rs.{cash:.2f}")
        print(f"  realized_pnl: Rs.{realized:.2f}")
        print(f"  orders: {orders_n}, positions: {positions_n}")
    except Exception as e:
        print(f"{path}: ERR {e}")
    print()
