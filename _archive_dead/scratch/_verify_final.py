import json
ps = json.load(open('data_cache/paper_state.json'))
print('paper_state.json:')
print(f'  cash = {ps["cash"]}')
print(f'  realized_pnl = {ps["realized_pnl"]}')
print(f'  computed return % = {ps["realized_pnl"] / 100000 * 100}')

sp = json.load(open('data_cache/performance/strategy_performance.json'))
print('strategy_performance.json:')
bd = sp.get('by_day', {})
total = sum(v.get('pnl', 0) or 0 for v in bd.values())
print(f'  by_day sum = {total}')
print(f'  by_day keys = {list(bd.keys())}')
for k, v in sorted(bd.items()):
    pnl = v.get('pnl', 0) or 0
    flag = ' [reset_conflict]' if v.get('reset_conflict') else ''
    print(f'    {k}: pnl={pnl}, trades={v.get("trades")}{flag}')