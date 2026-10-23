"""Check bot tick count from heartbeat."""
import json
with open('data_cache/liveness.json', 'r') as f:
    s = json.load(f)
print(f"Bot uptime: {s.get('uptime_sec')}")
print(f"Bot tick: {s.get('tick')}")
print(f"Bot state: {s.get('state')}")
print(f"VIX: {s.get('snapshot', {}).get('vix')}")