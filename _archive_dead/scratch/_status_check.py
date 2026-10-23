import json
from pathlib import Path

dec_path = Path('data_cache/quant_service_decisions.jsonl')
lines = dec_path.read_text(encoding='utf-8').splitlines()
print('Total decisions on file: ' + str(len(lines)))

# Show last 10 decisions with proper schema
print('\n=== Last 10 decisions ===')
for line in lines[-10:]:
    try:
        j = json.loads(line)
        ts = j.get('ts','')[:19].replace('T',' ')
        d = j.get('decision', {})
        dtype = d.get('type', '?')
        note = d.get('note', '')
        rat = d.get('rationale', '')
        strategy = d.get('strategy', '')
        legs = d.get('legs', [])
        n_legs = len(legs) if legs else 0
        underlying = d.get('underlying', '')
        msg = rat or note or dtype
        if len(msg) > 90: msg = msg[:87] + '...'
        leg_info = (' [' + str(n_legs) + ' legs]') if n_legs else ''
        print('  ' + ts + ' | ' + dtype.ljust(12) + ((' ' + underlying).ljust(10)) + leg_info.ljust(10) + ' | ' + msg)
    except Exception as e:
        print('  (parse err: ' + str(e)[:50] + ')')

# Count by action type
print('\n=== Decision type counts (today only, 2026-09-22) ===')
counts = {}
trade_actions = 0
for line in lines:
    try:
        j = json.loads(line)
        ts = j.get('ts','')
        if not ts.startswith('2026-09-22'):
            continue
        d = j.get('decision', {})
        dtype = d.get('type','?')
        counts[dtype] = counts.get(dtype, 0) + 1
        if dtype in ('OPEN', 'CLOSE', 'ADJUST'):
            trade_actions += 1
    except Exception:
        pass

for k, v in sorted(counts.items(), key=lambda x: -x[1]):
    print('  ' + k.ljust(15) + str(v))
print()
print('Total trade-impacting actions today: ' + str(trade_actions))
