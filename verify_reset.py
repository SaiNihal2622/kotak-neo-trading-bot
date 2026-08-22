import json
with open('data_cache/paper_state.json') as f:
    s = json.load(f)
print('paper_state.json:')
print(f'  cash: Rs.{s["cash"]}')
print(f'  realized_pnl: Rs.{s["realized_pnl"]}')
print(f'  positions: {len(s["positions"])}')
print(f'  orders: {len(s["orders"])}')
with open('data_cache/trades_state.json') as f:
    t = json.load(f)
print('trades_state.json:')
print(f'  trades: {len(t["trades"])}')
print(f'  symbol_to_trade: {len(t["symbol_to_trade"])}')
