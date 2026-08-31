#!/usr/bin/env python
"""Update brain_state.json with the 09:30 regular-open decision.
Replaces last_decision, bumps call_count_today, prepends previous last_decision to history.
"""
import json
import sys
from pathlib import Path

STATE_PATH = Path(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json")
NEW_DECISION_PATH = Path(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_actions.json")

def main() -> int:
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    new_decision = json.loads(NEW_DECISION_PATH.read_text(encoding="utf-8"))

    # Capture previous last_decision to prepend to history
    prev = state.get("last_decision", {})

    # Compact history entry: just ts, ist_time, bias, actions, actions_count, note
    prev_compact = {
        "ts": prev.get("ts"),
        "timestamp": prev.get("ts"),
        "ist_time": prev.get("ist_time"),
        "bias": prev.get("bias"),
        "actions": prev.get("actions", []),
        "actions_count": prev.get("actions_count", 0),
        "note": prev.get("note"),
    }

    # Update top-level fields
    state["today_date"] = "2026-08-28"
    state["call_count_today"] = state.get("call_count_today", 0) + 1
    state["timestamp"] = new_decision["ts"]

    # Replace last_decision with new
    state["last_decision"] = new_decision

    # Prepend previous to history
    history = state.get("history", [])
    history.insert(0, prev_compact)
    state["history"] = history

    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"OK: call_count_today={state['call_count_today']}, history len={len(history)}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
