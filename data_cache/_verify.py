import json
import os

p1 = r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_actions.json"
p2 = r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json"

# Read with utf-8-sig to handle BOM
with open(p1, encoding="utf-8-sig") as f:
    d1 = json.load(f)
print("brain_actions.json:")
print(f"  ist_time: {d1['ist_time']}")
print(f"  bias: {d1['bias']}")
print(f"  actions: {d1['actions']}")
print(f"  note: {d1['note'][:80]}")
print(f"  file size: {os.path.getsize(p1)} bytes")

print()
with open(p2, encoding="utf-8-sig") as f:
    d2 = json.load(f)
print("brain_state.json:")
print(f"  today_date: {d2['today_date']}")
print(f"  call_count_today: {d2['call_count_today']}")
print(f"  last_updated_ist: {d2['last_updated_ist']}")
print(f"  last_decision.ist_time: {d2['last_decision']['ist_time']}")
print(f"  last_decision.bias: {d2['last_decision']['bias']}")
print(f"  last_decision.actions: {d2['last_decision']['actions']}")
print(f"  history_len: {len(d2['history'])}")
print(f"  first_history.note: {d2['history'][0]['note'][:100]}")
print(f"  file size: {os.path.getsize(p2)} bytes")
