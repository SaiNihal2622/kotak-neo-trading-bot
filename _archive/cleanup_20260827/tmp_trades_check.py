import json
p = r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\trades_state.json'
try:
    with open(p, 'r', encoding='utf-8') as f:
        t = json.load(f)
    if isinstance(t, dict):
        positions = t.get('positions', {})
        orders = t.get('orders', {})
        trades = t.get('trades', {})
        npos_open = 0
        if isinstance(positions, dict):
            for v in positions.values():
                if isinstance(v, dict) and v.get('status', 'open') == 'open':
                    npos_open += 1
        elif isinstance(positions, list):
            npos_open = sum(1 for x in positions if isinstance(x, dict) and x.get('status') == 'open')
        norders_open = 0
        if isinstance(orders, dict):
            for v in orders.values():
                if isinstance(v, dict) and v.get('status', 'open') == 'open':
                    norders_open += 1
        elif isinstance(orders, list):
            norders_open = sum(1 for x in orders if isinstance(x, dict) and x.get('status') == 'open')
        print(f"trades_state: positions_total={len(positions)} open={npos_open} orders_total={len(orders)} open={norders_open} trades_total={len(trades)}")
    else:
        print(f"trades_state is {type(t).__name__} (not dict)")
except Exception as e:
    print(f"ERROR: {e}")