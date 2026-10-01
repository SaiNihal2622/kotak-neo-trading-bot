"""Force-action: resume + restart brain_daemon (now in watchdog mode)."""
import json, os
from pathlib import Path

target = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\mavis_force_action.json')
# PowerShell command: resume service, set to auto, start it
ps_cmd = (
    "& 'C:\\Tools\\nssm\\nssm-2.24\\win64\\nssm.exe' set KotakBrainDaemon Start SERVICE_AUTO_START; "
    "& 'C:\\Tools\\nssm\\nssm-2.24\\win64\\nssm.exe' continue-service KotakBrainDaemon; "
    "Start-Sleep -Seconds 3; "
    "& 'C:\\Tools\\nssm\\nssm-2.24\\win64\\nssm.exe' status KotakBrainDaemon"
)
payload = {
    "action": "RUN_COMMAND",
    "command": [
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd,
    ],
    "timeout": 30,
    "reason": "phase12: resume brain_daemon and confirm watchdog mode",
    "ts": "2026-10-01T17:28:00+05:30",
}
tmp = target.with_suffix(".json.tmp")
tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
os.replace(tmp, target)
print(f"wrote force action: {ps_cmd[:80]}...")