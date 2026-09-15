#!/usr/bin/env python
import json
gs = json.loads(open('data_cache/global_state.json', encoding='utf-8').read())
print(f'  ts: {gs.get("ts")}')
print(f'  instruments: {len(gs.get("instruments", {}))}')
for t, d in list(gs.get('instruments', {}).items())[:8]:
    name = d.get('name', t)
    price = d.get('price', 0)
    pct = d.get('pct_1d', 0)
    if price:
        sign = '+' if pct > 0 else ''
        print(f'  {name:14} {t:14} {price:>10.2f} {sign}{pct:.2f}%')
