"""Show current positions."""
import json
ps = json.load(open('data_cache/paper_state.json'))
print(f"Cash: {ps.get('cash')}")
print(f"Realized: {ps.get('realized_pnl')}")
print("Positions:")
for sym, p in ps.get('positions', {}).items():
    if p.get('qty', 0) != 0:
        print(f"  {sym}: qty={p.get('qty')} avg={p.get('avg_price')} ltp={p.get('ltp')} pnl={p.get('pnl')}")
