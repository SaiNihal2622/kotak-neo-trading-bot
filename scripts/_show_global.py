#!/usr/bin/env python
import json
with open('data_cache/global_state.json', encoding='utf-8') as f:
    gs = json.load(f)
insts = gs.get('instruments', {})
print(f'global_state.json: {len(insts)} instruments')
print(f'  ts: {gs.get("ts", "?")}')
for ticker, data in sorted(insts.items()):
    name = data.get('name', ticker)
    last = data.get('last')
    chg = data.get('chg_24h')
    if last is not None and chg is not None:
        sign = '+' if chg > 0 else ''
        print(f'  {name:14} {ticker:14} last={last:>10.2f} chg24h={sign}{chg:.2f}%')
    else:
        print(f'  {name:14} {ticker:14} no data')
