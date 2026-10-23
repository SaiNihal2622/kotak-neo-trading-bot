"""Today's P&L check."""
import json
with open('data_cache/paper_state.json', 'r', encoding='utf-8') as f:
    s = json.load(f)

cash = s['cash']
realized = s['realized_pnl']
unrealized = sum(p.get('pnl', 0) for p in s['positions'].values())
total = realized + unrealized

print(f"Cash: Rs.{cash:,.2f}")
print(f"Realized P&L: Rs.{realized:,.2f}")
print(f"Unrealized P&L: Rs.{unrealized:,.2f}")
print(f"TOTAL P&L: Rs.{total:,.2f}")
print(f"Open positions: {len(s['positions'])}")
print()
print("Open positions:")
for sym, pos in s['positions'].items():
    print(f"  {sym}: qty={pos['qty']} avg=Rs.{pos['avg_price']:.2f} ltp=Rs.{pos['ltp']:.2f} pnl=Rs.{pos.get('pnl', 0):,.0f}")
print()
print(f"Starting capital: Rs.100,000.00")
print(f"Current equity: Rs.{cash + unrealized:,.2f}")
print(f"Return: {(cash + unrealized - 100000) / 100000 * 100:+.2f}%")