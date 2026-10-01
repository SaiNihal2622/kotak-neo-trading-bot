"""Force-action: set BRAIN_DAEMON_MODE=watchdog machine-wide + restart service."""
import json, os
from pathlib import Path

target = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\mavis_force_action.json')
payload = {
    "action": "RUN_COMMAND",
    "command": [
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
        (
            "[Environment]::SetEnvironmentVariable('BRAIN_DAEMON_MODE','watchdog','Machine'); "
            "Write-Host ('BRAIN_DAEMON_MODE=' + [Environment]::GetEnvironmentVariable('BRAIN_DAEMON_MODE','Machine')); "
            "& 'C:\\Tools\\nssm\\nssm-2.24\\win64\\nssm.exe' set KotakBrainDaemon AppEnvironmentExtra 'PYTHONIOENCODING=utf-8;BRAIN_DAEMON_MODE=watchdog'; "
            "& 'C:\\Tools\\nssm\\nssm-2.24\\win64\\nssm.exe' restart KotakBrainDaemon"
        )
    ],
    "timeout": 30,
    "reason": "phase12: switch brain_daemon to watchdog mode (Mavis cron runs cycles)",
    "ts": "2026-10-01T17:25:00+05:30",
}
tmp = target.with_suffix(".json.tmp")
tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
os.replace(tmp, target)
print(f"wrote force action to {target}")