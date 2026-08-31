#!/usr/bin/env python3
"""Surgically update brain_state.json's `last_decision` field, preserve history.

The new last_decision is read from data_cache/brain_actions.json.
The history array is preserved as-is.
"""
import json
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot")
ACTIONS = ROOT / "data_cache" / "brain_actions.json"
STATE = ROOT / "data_cache" / "brain_state.json"

with open(ACTIONS, "r", encoding="utf-8") as f:
    new_decision = json.load(f)

with open(STATE, "r", encoding="utf-8") as f:
    state = json.load(f)

old_last = state.get("last_decision", {})
print(f"OLD last_decision.ist_time: {old_last.get('ist_time', '?')}")
print(f"NEW last_decision.ist_time: {new_decision.get('ist_time', '?')}")
print(f"OLD last_decision.bias: {old_last.get('bias', '?')}")
print(f"NEW last_decision.bias: {new_decision.get('bias', '?')}")
print(f"OLD last_decision.actions_count: {old_last.get('actions_count', '?')}")
print(f"NEW last_decision.actions_count: {new_decision.get('actions_count', '?')}")
print(f"history entries preserved: {len(state.get('history', []))}")
print(f"call_count_today: {state.get('call_count_today', '?')} -> {state.get('call_count_today', 0) + 1}")

state["last_decision"] = new_decision
state["call_count_today"] = state.get("call_count_today", 0) + 1
state["timestamp"] = new_decision.get("ts", "")

with open(STATE, "w", encoding="utf-8") as f:
    json.dump(state, f, indent=2, ensure_ascii=False)

print(f"OK. brain_state.json updated. New size: {STATE.stat().st_size} bytes")
