"""Atomically write force-action to reload brain_daemon."""
import json
from pathlib import Path

payload = {
    "action": "RUN_COMMAND",
    "command": ["taskkill", "/PID", "19448", "/F"],
    "timeout": 15,
    "reason": "phase7-final: reload brain_daemon with bayesian+online_learner+regime_detector",
    "ts": "2026-10-01T01:53:30+05:30",
}
target = Path(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\mavis_force_action.json")
# Atomic write
tmp = target.with_suffix(".json.tmp")
tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
import os
os.replace(tmp, target)
print(f"wrote {target}")
print(target.read_text(encoding="utf-8"))