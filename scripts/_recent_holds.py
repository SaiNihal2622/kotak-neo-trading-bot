#!/usr/bin/env python
import json
with open('data_cache/quant_service_decisions.jsonl', encoding='utf-8') as f:
    lines = [l for l in f if l.startswith('{2026') and '"type": "HOLD"' in l]
print(f'Total HOLDs today: {len(lines)}')
for line in lines[-5:]:
    d = json.loads(line)
    rat = d['decision'].get('rationale', '')
    print(f'  {d["ts"]} | conf={d["decision"].get("confidence", 0):.2f}')
    print(f'    {rat[:250]}')
    print()
