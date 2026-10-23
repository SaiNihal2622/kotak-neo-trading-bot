"""Check broken-condor marker state."""
import json
with open('data_cache/_broken_condor.json', 'r', encoding='utf-8') as f:
    bc = json.load(f)
print(f"consumed: {bc.get('consumed')}")
print(f"n_closed: {bc.get('n_closed')}")
print(f"consumed_at: {bc.get('consumed_at')}")