"""Force-action: explicitly start NSSM service."""
import json, os
from pathlib import Path

target = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\mavis_force_action.json')
ps_cmd = (
    "& 'C:\\Tools\\nssm\\nssm-2.24\\win64\\nssm.exe' set KotakBrainDaemon Start SERVICE_AUTO_START; "
    "& 'C:\\Tools\\nssm\\nssm-2.24\\win64\\nssm.exe' start KotakBrainDaemon; "
    "Start-Sleep -Seconds 3; "
    "& 'C:\\Tools\\nssm\\nssm-2.24\\win64\\nssm.exe' status KotakBrainDaemon"
)
payload = {
    "action": "RUN_COMMAND",
    "command": [
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd,
    ],
    "timeout": 30,
    "reason": "phase12: explicitly start KotakBrainDaemon NSSM service",
    "ts": "2026-10-01T17:30:00+05:30",
}
tmp = target.with_suffix(".json.tmp")
tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
os.replace(tmp, target)
print(f"wrote start force action")