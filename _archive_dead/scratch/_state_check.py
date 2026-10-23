"""Check paper state."""
import json
with open('data_cache/paper_state.json', 'r', encoding='utf-8') as f:
    s = json.load(f)
print(f"Cash: {s['cash']}")
print(f"Realized: {s['realized_pnl']}")
print(f"Positions: {len(s['positions'])}")
for sym, pos in s['positions'].items():
    print(f"  {sym}: qty={pos['qty']} pnl={pos.get('pnl', 0):.0f}")