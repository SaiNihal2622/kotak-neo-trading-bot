#!/usr/bin/env python3
"""Update last_decision in brain_state.json, preserve history."""
import json
import sys
from datetime import datetime, timezone, timedelta

STATE_PATH = r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json"
ACTIONS_PATH = r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_actions.json"

# Load existing state
with open(STATE_PATH, "r", encoding="utf-8") as f:
    state = json.load(f)

# Load new decision
with open(ACTIONS_PATH, "r", encoding="utf-8") as f:
    new_decision = json.load(f)

# Update top-level fields
now_utc = datetime.now(timezone.utc)
ist = now_utc + timedelta(hours=5, minutes=30)
state["timestamp"] = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
state["call_count_today"] = state.get("call_count_today", 0) + 1

# Append previous decision to history (preserve chain)
prev_decision = state.get("last_decision")
if prev_decision:
    history_entry = {
        "ts": prev_decision.get("ts"),
        "timestamp": prev_decision.get("ts"),
        "ist_time": prev_decision.get("ist_time"),
        "bias": prev_decision.get("bias"),
        "actions": prev_decision.get("actions", []),
        "actions_count": prev_decision.get("actions_count", 0),
        "note": prev_decision.get("note", ""),
    }
    state.setdefault("history", []).insert(0, history_entry)

# Set new last_decision
state["last_decision"] = new_decision

# Write back with utf-8 to preserve any unicode
with open(STATE_PATH, "w", encoding="utf-8") as f:
    json.dump(state, f, ensure_ascii=False, indent=2)

print(f"Updated brain_state.json: last_decision={new_decision['ist_time']}, call_count_today={state['call_count_today']}, history entries={len(state.get('history', []))}")
