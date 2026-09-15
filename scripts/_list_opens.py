#!/usr/bin/env python
import json
with open('data_cache/quant_service_decisions.jsonl', encoding='utf-8') as f:
    lines = f.readlines()
opens = []
for l in lines:
    if l.startswith('{'):
        d = json.loads(l)
        if d['decision'].get('type') == 'OPEN':
            opens.append(d)
print(f'Total OPENs in log: {len(opens)}')
for o in opens:
    ts = o['ts']
    udl = o['decision'].get('underlying')
    strat = o['decision'].get('strategy')
    legs = o['decision'].get('legs', [])
    leg_str = ' '.join(f"{l.get('side','')[:1]}{l.get('strike','')}{l.get('opt_type','')}x{l.get('qty',0)}" for l in legs)
    print(f'  {ts} | {udl} {strat} | {leg_str}')

# also check quant_actions for placed_legs history
import os
qa = 'data_cache/quant_actions.json'
if os.path.exists(qa):
    q = json.loads(open(qa, encoding='utf-8').read())
    print(f'\nCurrent quant_actions.json:')
    print(f'  ts={q.get("ts")} consumed={q.get("consumed")} placed_legs={q.get("placed_legs")}')
    if q.get('failed'):
        print(f'  FAILED: {q.get("failed_reason")}')

qf = 'data_cache/quant_actions.failed.json'
if os.path.exists(qf):
    fails = json.loads(open(qf, encoding='utf-8').read())
    if isinstance(fails, list):
        print(f'\nFailed actions history: {len(fails)} entries')
        for f in fails[-3:]:
            print(f'  ts={f.get("ts")} actions={len(f.get("actions",[]))} placed_legs={f.get("placed_legs")} reason={f.get("failed_reason")}')
