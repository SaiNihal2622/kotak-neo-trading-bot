"""Post-mortem on today's trades."""
import json
from datetime import datetime

with open('data_cache/paper_state.json', 'r', encoding='utf-8') as f:
    s = json.load(f)

# All orders today
orders = s.get('orders', {})
today = '2026-09-29'
today_orders = []
for oid, o in orders.items():
    if o.get('placed_at', '').startswith(today) and o.get('status') == 'complete':
        today_orders.append(o)

print(f"Today FILLED orders: {len(today_orders)}")
print()
# Group by symbol
by_symbol = {}
for o in today_orders:
    sym = o.get('symbol', '')
    by_symbol.setdefault(sym, []).append(o)

for sym, sym_orders in sorted(by_symbol.items()):
    print(f"\n{'='*70}")
    print(f"Symbol: {sym}")
    print(f"{'='*70}")
    for o in sorted(sym_orders, key=lambda x: x.get('placed_at', '')):
        ts = o.get('placed_at', '')[:19]
        side = o.get('side')
        qty = o.get('qty')
        fill = o.get('avg_fill_price', 0)
        cost = qty * fill
        tag = o.get('tag', '')[:20]
        print(f"  {ts} {side} {qty:>4} @ Rs.{fill:>6.2f}  cost=Rs.{cost:>9,.0f}  tag={tag}")

print()
print("\n--- Open positions (current state) ---")
for sym, pos in s['positions'].items():
    qty = pos['qty']
    avg = pos['avg_price']
    ltp = pos['ltp']
    pnl = pos.get('pnl', 0)
    pnl_pct = (ltp - avg) / avg * 100 if avg else 0
    print(f"  {sym}: qty={qty:>4} avg=Rs.{avg:>6.2f} ltp=Rs.{ltp:>6.2f} pnl=Rs.{pnl:>+8,.0f} ({pnl_pct:+.1f}%)")