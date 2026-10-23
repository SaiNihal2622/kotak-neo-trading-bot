"""Check today's filled orders."""
import json
with open('data_cache/paper_state.json', 'r', encoding='utf-8') as f:
    s = json.load(f)
orders = s.get('orders', {})
today = '2026-09-29'
today_filled = []
today_rejected = 0
for oid, o in orders.items():
    if o.get('placed_at', '').startswith(today):
        if o.get('status') == 'complete':
            today_filled.append(o)
        elif o.get('status') == 'rejected':
            today_rejected += 1
print(f'Today filled: {len(today_filled)}')
print(f'Today rejected: {today_rejected}')

# Show the last 25 filled orders (most recent)
today_filled.sort(key=lambda x: x.get('placed_at', ''))
print('\nLast 25 filled orders today:')
for o in today_filled[-25:]:
    ts = o.get('placed_at', '')[11:19]
    side = o.get('side')
    qty = o.get('qty')
    sym = o.get('symbol', '')[:25]
    price = o.get('avg_fill_price', 0)
    tag = o.get('tag', '')[:25]
    print(f"  {ts} {side:<4} {qty:>4} {sym:<25} @ Rs.{price:>6.2f} tag={tag}")