"""Force-action: resume NSSM service + restart with watchdog env."""
import json, os
from pathlib import Path

target = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\mavis_force_action.json')
# Use a single powershell command that:
# 1. Sets the service start mode to auto
# 2. Removes pause
# 3. Starts (or restarts) the service
# 4. Returns the final status
ps_cmd = (
    "$ErrorActionPreference = 'Stop'; "
    "$nssm = 'C:\\Tools\\nssm\\nssm-2.24\\win64\\nssm.exe'; "
    "& $nssm set KotakBrainDaemon Start SERVICE_AUTO_START 2>&1; "
    "& $nssm continue-service KotakBrainDaemon 2>&1; "
    "Start-Sleep -Seconds 2; "
    "& $nssm start KotakBrainDaemon 2>&1; "
    "Start-Sleep -Seconds 3; "
    "Write-Host '---STATUS---'; "
    "& $nssm status KotakBrainDaemon 2>&1"
)
payload = {
    "action": "RUN_COMMAND",
    "command": [
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd,
    ],
    "timeout": 30,
    "reason": "phase12-final: resume brain_daemon service with watchdog mode",
    "ts": "2026-10-01T18:30:00+05:30",
}
tmp = target.with_suffix(".json.tmp")
tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
os.replace(tmp, target)
print(f"wrote resume action")