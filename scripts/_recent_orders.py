#!/usr/bin/env python
import json
ps = json.loads(open('data_cache/paper_state.json', encoding='utf-8').read())
orders = ps.get('orders', {})
recent = sorted(orders.values(), key=lambda o: o.get('placed_at', ''), reverse=True)[:15]
for o in recent:
    placed = o.get('placed_at', '?')[:19]
    sym = o.get('symbol', '?')
    side = o.get('side')
    qty = o.get('qty')
    tag = o.get('tag', '?')[:30]
    status = o.get('status', '?')
    print(f'  {placed} | {sym} | {side} qty={qty} | tag={tag} | status={status}')
print()
print('positions in state:')
for sym, p in ps.get('positions', {}).items():
    qty = p.get('qty')
    avg = p.get('avg_price')
    ltp = p.get('ltp')
    expiry = p.get('expiry')
    print(f'  {sym}: qty={qty} avg={avg} ltp={ltp} expiry={expiry}')
print()
print('cash:', ps.get('cash'))
print('realized_pnl:', ps.get('realized_pnl'))
