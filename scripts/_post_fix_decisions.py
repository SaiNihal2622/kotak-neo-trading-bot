#!/usr/bin/env python
import json
with open('data_cache/quant_service_decisions.jsonl', encoding='utf-8') as f:
    lines = f.readlines()

# Filter to after 12:30 (after my production fixes took effect)
post = [l for l in lines if any(h in l for h in ('12:3', '12:4', '12:5', '13:', '14:0')) and l.startswith('{2026-09-02T1')]
print(f'Brain decisions from 12:30 onwards: {len(post)}')
print()

# Show last 8 with full rationale
for line in post[-8:]:
    d = json.loads(line)
    typ = d['decision']['type']
    rat = d['decision'].get('rationale', '')[:280]
    if rat:
        print(f'  {d["ts"]} | {typ}')
        print(f'    {rat}')
        print()

# Also show distribution of HOLD reasons
from collections import Counter
hold_reasons = []
for line in post:
    d = json.loads(line)
    if d['decision']['type'] == 'HOLD':
        rat = d['decision'].get('rationale', '').lower()
        if 'no sector theme' in rat or 'sector confirmation' in rat:
            hold_reasons.append('no_sector_confirmation')
        elif 'sub-threshold' in rat:
            hold_reasons.append('sub_threshold_drift')
        elif 'noise' in rat:
            hold_reasons.append('noise')
        elif 'vix' in rat and 'low' in rat:
            hold_reasons.append('low_vix')
        elif 'tight' in rat or 'range' in rat:
            hold_reasons.append('tight_range')
        else:
            hold_reasons.append('other')
print('HOLD reasons since 12:30:', Counter(hold_reasons))
