#!/usr/bin/env python3
"""Update brain_state.json: replace last_decision with brain_actions.json content, add old last_decision to history, update counters."""
import json
from pathlib import Path
from datetime import datetime, timezone

BASE = Path(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache")
state_path = BASE / "brain_state.json"
actions_path = BASE / "brain_actions.json"

# Load both
with open(state_path, "r", encoding="utf-8") as f:
    state = json.load(f)
with open(actions_path, "r", encoding="utf-8") as f:
    new_decision = json.load(f)

# Save the old last_decision for history (we want to keep it as a history entry)
old_decision = state.get("last_decision", {})

# Ensure old_decision is properly shaped for history
history_entry = {
    "ts": old_decision.get("ts"),
    "timestamp": old_decision.get("timestamp"),
    "ist_time": old_decision.get("ist_time"),
    "bias": old_decision.get("bias"),
    "source": old_decision.get("source"),
    "max_positions": old_decision.get("max_positions"),
    "actions": old_decision.get("actions", []),
    "market_session": old_decision.get("market_session", "regular"),
    "vix": old_decision.get("vix", state.get("vix", 11.165)),
    "risk_budget_pct": old_decision.get("risk_budget_pct", 0),
    "bias_decision": old_decision.get("bias_decision", old_decision.get("bias")),
    "macro_in_blackout": old_decision.get("macro_in_blackout", False),
    "decision_summary": old_decision.get("decision_summary"),
    "rationale": old_decision.get("rationale"),
    "risk_budget_reasoning": old_decision.get("risk_budget_reasoning"),
    "candle_regime_evidence": old_decision.get("candle_regime_evidence"),
    "macro_evidence": old_decision.get("macro_evidence"),
    "research_evidence": old_decision.get("research_evidence"),
    "open_positions_summary": old_decision.get("open_positions_summary"),
    "actions_count": old_decision.get("actions_count", len(old_decision.get("actions", []))),
}

# Prepend to history (limit to most recent 200 entries)
history = state.get("history", [])
history.insert(0, history_entry)
state["history"] = history[:200]

# Update counters
state["call_count_today"] = state.get("call_count_today", 0) + 1
state["timestamp"] = new_decision.get("ts")

# Replace last_decision with the new one
state["last_decision"] = new_decision

# Write back atomically
tmp = state_path.with_suffix(".json.tmp")
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(state, f, ensure_ascii=False, indent=2)
tmp.replace(state_path)

print(f"brain_state.json updated:")
print(f"  call_count_today: {state['call_count_today']}")
print(f"  timestamp: {state['timestamp']}")
print(f"  last_decision.ist_time: {new_decision.get('ist_time')}")
print(f"  last_decision.bias: {new_decision.get('bias')}")
print(f"  last_decision.actions_count: {new_decision.get('actions_count')}")
print(f"  history entries: {len(state['history'])}")
print(f"  history[0].ist_time: {history[0].get('ist_time')}")
