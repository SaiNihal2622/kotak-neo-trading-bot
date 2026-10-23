"""Count today's orders."""
import json
with open('data_cache/paper_state.json', 'r', encoding='utf-8') as f:
    s = json.load(f)
orders = s.get('orders', {})
today = '2026-09-29'
today_count = 0
today_placed = 0
today_rejected = 0
for oid, o in orders.items():
    if o.get('placed_at', '').startswith(today):
        today_count += 1
        if o.get('status') == 'complete':
            today_placed += 1
        elif o.get('status') == 'rejected':
            today_rejected += 1
print(f"Today orders: {today_count}")
print(f"  placed: {today_placed}")
print(f"  rejected: {today_rejected}")
print(f"Open positions: {len(s['positions'])}")
print(f"Cash: Rs.{s['cash']}")
print(f"Realized: Rs.{s['realized_pnl']}")