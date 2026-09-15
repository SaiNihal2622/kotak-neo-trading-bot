#!/usr/bin/env python
import json
with open('data_cache/quant_service_decisions.jsonl', encoding='utf-8') as f:
    lines = f.readlines()
print(f'total decisions in log: {len(lines)}')
today = [l for l in lines if l.startswith('{2026-09-02')]
print(f'today: {len(today)}')
for l in lines[-3:]:
    d = json.loads(l)
    typ = d['decision']['type']
    print(f'  {d["ts"]} | {typ}')
