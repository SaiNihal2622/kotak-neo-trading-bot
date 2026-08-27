"""One-shot update: replace last_decision in brain_state.json with 10:40 tick."""
import json
from pathlib import Path

state_path = Path(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json")
actions_path = Path(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_actions.json")

state = json.loads(state_path.read_text(encoding="utf-8"))
new_decision = json.loads(actions_path.read_text(encoding="utf-8"))

# Update last_decision entirely
state["last_decision"] = new_decision
state["call_count_today"] = 20

# Add history entry
if "history" in state:
    state["history"].append({
        "ist_time": new_decision["ist_time"],
        "bias": new_decision["bias"],
        "note": new_decision["note"],
        "actions": new_decision["actions"]
    })

# Update history addendum
state["last_decision_history_addendum"] = (
    "10:40 tick: downward drift since 10:35. NIFTY -5.60 to 24127.60, BANKNIFTY -23.70 to 57422.00. "
    "PE sides tightened: NIFTY 24100 PE 33.20->27.60 (7.60 above trigger at 24120), "
    "BANKNIFTY 57400 PE 45.70->22.00 (2.00 above trigger at 57420 — TIGHTEST condition today). "
    "CE sides much safer. VIX compressed 11.58->11.49. 16th HOLD tick of the day. "
    "Escalation: if BANKNIFTY<57415 OR NIFTY<24115 next tick, CLOSE BANKNIFTY IC."
)

state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"Updated {state_path}: call_count_today={state['call_count_today']}, history_len={len(state.get('history', []))}")
