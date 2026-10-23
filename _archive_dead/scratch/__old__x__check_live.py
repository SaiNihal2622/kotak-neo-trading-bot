"""Check liveness."""
import json
with open('data_cache/liveness.json', 'r') as f:
    s = json.load(f)
print(f"Bot PID: {s.get('pid')}")
print(f"Bot uptime: {s.get('uptime_sec')}")
print(f"Positions: {s.get('snapshot', {}).get('open_positions', 0)}")