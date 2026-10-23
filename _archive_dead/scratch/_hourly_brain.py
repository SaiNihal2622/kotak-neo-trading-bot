import json
from pathlib import Path
from collections import Counter

p = Path('data_cache/quant_service_decisions.jsonl')
lines = p.read_text(encoding='utf-8').splitlines()
hourly = Counter()
trade_actions = Counter()
for line in lines:
    try:
        j = json.loads(line)
        ts = j.get('ts','')
        if not ts.startswith('2026-09-22'): continue
        h = ts[11:13]
        hourly[h] += 1
        d = j.get('decision', {})
        t = d.get('type','')
        if t in ('OPEN','CLOSE','ADJUST'):
            trade_actions[t] += 1
    except Exception:
        pass

print('Hourly brain activity today:')
for h in sorted(hourly.keys()):
    print('  ' + h + ':00 IST  -  ' + str(hourly[h]).rjust(4) + ' decisions')
print()
print('Total trade actions: OPEN=' + str(trade_actions['OPEN']) + ', CLOSE=' + str(trade_actions['CLOSE']) + ', ADJUST=' + str(trade_actions['ADJUST']))
