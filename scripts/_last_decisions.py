#!/usr/bin/env python
import json, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
with open('data_cache/quant_service_decisions.jsonl', encoding='utf-8') as f:
    lines = f.readlines()
for line in lines[-4:]:
    d = json.loads(line)
    typ = d['decision']['type']
    legs = d['decision'].get('legs', [])
    leg_str = ' | '.join(f"{l.get('side')[:1]}{l.get('strike')}{l.get('opt_type')}@{l.get('qty')}" for l in legs)
    rat = d['decision'].get('rationale', '')[:280]
    print(f"  {d['ts']} | {typ} | {d['decision'].get('underlying')} {d['decision'].get('strategy')} | conf={d['decision'].get('confidence', 0):.2f}")
    print(f"    legs: {leg_str}")
    print(f"    target={d['decision'].get('target')} stop={d['decision'].get('stop')}")
    print(f"    rationale: {rat}")
    print()
