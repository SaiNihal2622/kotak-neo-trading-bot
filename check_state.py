"""Read paper state and show orders/positions."""
import json

with open("data_cache/paper_state.json") as f:
    s = json.load(f)
print(f"orders: {len(s['orders'])}")
for oid, o in s["orders"].items():
    print(f"  {oid[:25]} {o['symbol']:32s} side={o['side']:5s} status={o['status']:10s} filled={o['filled_qty']:4d} fill_price={o['avg_fill_price']}")
print(f"\npositions: {len(s['positions'])}")
for sym, p in s["positions"].items():
    print(f"  {sym}: qty={p['qty']} avg={p['avg_price']:.2f} ltp={p['ltp']:.2f} pnl={p['pnl']:.2f}")
print(f"\ncash: {s['cash']}, realized_pnl: {s['realized_pnl']}")
