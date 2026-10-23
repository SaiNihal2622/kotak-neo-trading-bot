"""Check if positions closed."""
import json
with open('data_cache/paper_state.json', 'r', encoding='utf-8') as f:
    s = json.load(f)
print(f"Cash: Rs.{s['cash']:,.2f}")
print(f"Realized P&L: Rs.{s['realized_pnl']:,.2f}")
print(f"Open positions: {len(s['positions'])}")
for sym, pos in s['positions'].items():
    print(f"  {sym}: qty={pos['qty']} pnl=Rs.{pos.get('pnl', 0):,.0f}")