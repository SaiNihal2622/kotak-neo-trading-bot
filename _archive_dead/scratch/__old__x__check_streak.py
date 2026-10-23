"""Check live_go_status.json."""
import json
with open('data_cache/live_go_status.json', 'r', encoding='utf-8') as f:
    s = json.load(f)
for k, v in s.items():
    print(f"{k}: {v}")