import json
sp = json.load(open('data_cache/performance/strategy_performance.json', encoding='utf-8'))
print('by_day keys:')
for k, v in (sp.get('by_day') or {}).items():
    print(f'  {k}: {v}')
print()
print(f'cumulative_realized_pnl = {sp.get("cumulative_realized_pnl")}')
print(f'sharpe_30d = {sp.get("sharpe_30d")}')
print(f'win_rate = {sp.get("win_rate")}')
print(f'total_trades = {sp.get("total_trades")}')
print()
print('reconciliation:')
print(json.dumps(sp.get('reconciliation'), indent=2))