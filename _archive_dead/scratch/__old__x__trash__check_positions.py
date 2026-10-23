"""Check current paper state positions."""
import json
with open('data_cache/paper_state.json', 'r', encoding='utf-8') as f:
    s = json.load(f)
print(f"cash: {s['cash']}")
print(f"realized_pnl: {s['realized_pnl']}")
print(f"positions: {len(s['positions'])}")
for sym, pos in s['positions'].items():
    print(f"  {sym}: qty={pos['qty']} avg={pos['avg_price']:.2f} ltp={pos['ltp']:.2f} pnl={pos['pnl']:.0f}")