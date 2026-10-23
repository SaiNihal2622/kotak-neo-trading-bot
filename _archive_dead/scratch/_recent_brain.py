"""Recent brain activity."""
import sys
sys.stdout.reconfigure(encoding='utf-8')
with open('data_cache/quant_service.log', 'r', encoding='utf-8') as f:
    lines = f.readlines()
recent = lines[-50:]
for line in recent:
    if any(k in line for k in ['STRATEGY-LIBRARY', 'ATOMIC-DOWNGRADE', 'ACTION-WRITTEN', 'LLM-DECISION', 'OPEN', 'PLACE', 'REJECT', 'no-match', 'CONFLICT', 'dedup']):
        print(line.rstrip())