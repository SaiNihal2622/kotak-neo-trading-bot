"""Update brain_state.json: set last_decision to 11:40 decision, prepend to history, bump counter."""
import json
import os
from datetime import datetime, timezone, timedelta

ist = timezone(timedelta(hours=5, minutes=30))
now_ist = datetime.now(ist)
now_utc = datetime.now(timezone.utc)

state_path = r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json"
actions_path = r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_actions.json"

with open(actions_path, "r", encoding="utf-8") as f:
    new_decision = json.load(f)

with open(state_path, "r", encoding="utf-8") as f:
    state = json.load(f)

old_last = state.get("last_decision", {})
history = state.get("history", [])

# Build new last_decision = the decision we just wrote (already has full schema)
new_last = dict(new_decision)
new_last["timestamp"] = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
new_last["call_count_today"] = state.get("call_count_today", 0) + 1

# Add the previous last_decision to the top of history (chronological order is oldest-first; we prepend)
if old_last:
    history_entry = dict(old_last)
    history.insert(0, history_entry)

# Keep history bounded to last 80 entries to avoid runaway growth
if len(history) > 80:
    history = history[:80]

state["last_decision"] = new_last
state["timestamp"] = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
state["call_count_today"] = new_last["call_count_today"]
state["history"] = history

with open(state_path, "w", encoding="utf-8") as f:
    json.dump(state, f, indent=2, ensure_ascii=False)

print(f"UPDATED {state_path}")
print(f"  call_count_today={state['call_count_today']}")
print(f"  last_decision.ist_time={new_last['ist_time']}")
print(f"  last_decision.bias={new_last['bias']}")
print(f"  last_decision.actions={len(new_last['actions'])}")
print(f"  history.len={len(history)}")
print(f"  file_size={os.path.getsize(state_path)} bytes")
