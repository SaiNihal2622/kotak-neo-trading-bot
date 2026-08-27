import json
p = r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\paper_state.json'
try:
    with open(p, 'r', encoding='utf-8') as f:
        s = json.load(f)
    cash = s.get('cash')
    realized = s.get('realized_pnl')
    orders = s.get('orders', {})
    positions = s.get('positions', [])
    if isinstance(positions, dict):
        positions = list(positions.values())
    npos = len([pp for pp in positions if isinstance(pp, dict) and pp.get('qty', 0) != 0])
    print(f"cash={cash} realized={realized} orders={len(orders)} open_positions={npos}")
except Exception as e:
    print(f"ERROR: {e}")