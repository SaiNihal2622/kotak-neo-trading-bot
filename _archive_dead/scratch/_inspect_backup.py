import json
b = json.load(open('data_cache/backups/20260917_230001/paper_state.json'))
print('cash =', b['cash'])
print('realized_pnl =', b['realized_pnl'])
print('computed realized = cash - 100000 =', b['cash'] - 100000)
print('orders count =', len(b.get('orders', {})))
print('positions:')
positions = b.get('positions') or {}
for sym, pos in positions.items():
    qty = pos.get('qty')
    avg = pos.get('avg_price')
    ltp = pos.get('ltp', 'n/a')
    if qty != 0:
        print(f'  {sym}: qty={qty} avg={avg} ltp={ltp}')
print('all positions (incl zero qty):')
for sym, pos in positions.items():
    qty = pos.get('qty')
    avg = pos.get('avg_price')
    if qty == 0:
        print(f'  {sym}: qty=0 (closed)')