"""Phase 9 force restart brain_daemon."""
import json, os
from pathlib import Path

target = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\mavis_force_action.json')
payload = {
    "action": "RUN_COMMAND",
    "command": ["taskkill", "/PID", "28520", "/F"],
    "timeout": 15,
    "reason": "phase9: live trader intel (real-time analyst consensus)",
    "ts": "2026-10-01T13:15:00+05:30",
}
tmp = target.with_suffix(".json.tmp")
tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
os.replace(tmp, target)
print(f"wrote {target}")