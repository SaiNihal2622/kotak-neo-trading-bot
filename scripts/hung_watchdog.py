"""Hung-service watchdog for the Kotak trading system.

NSSM auto-restarts a service that CRASHES, but not one that is HUNG
(process alive, main loop stalled). This watchdog detects the hung case
by checking liveness freshness and restarts the service if stale.

Run every 5 min via scheduled task (or the existing kotak-bot-watchdog
cron). Idempotent, safe to run repeatedly.

Usage:
    .venv\\Scripts\\python.exe scripts\\hung_watchdog.py
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
DATA = ROOT / 'data_cache'
LOG = DATA / 'hung_watchdog.log'
NSSM = r'C:\Tools\nssm\nssm-2.24\win64\nssm.exe'

# (service, liveness_file, max_age_sec)
WATCH = [
    ('KotakBotPaper', 'liveness.json', 300),        # bot ticks ~1/s; 5min stale = hung
    ('KotakQuantService', 'quant_service_state.json', 300),
]

# A service that is legitimately idle (market closed, overnight) still
# updates its liveness/state file. So staleness here means genuinely hung.


def log(msg: str) -> None:
    line = f"[{datetime.now().astimezone().isoformat(timespec='seconds')}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG, 'a', encoding='utf-8') as fh:
            fh.write(line + '\n')
    except Exception:
        pass


def _file_age_sec(path: Path) -> float:
    if not path.exists():
        return float('inf')
    return time.time() - path.stat().st_mtime


def _service_state(svc: str) -> str:
    try:
        out = subprocess.run(['sc.exe', 'query', svc], capture_output=True,
                             text=True, timeout=15).stdout
        for line in out.splitlines():
            if 'STATE' in line:
                # "STATE : 4  RUNNING" -> "RUNNING"
                return line.split(':', 1)[1].strip().split()[-1]
    except Exception:
        pass
    return 'UNKNOWN'


def _restart(svc: str) -> None:
    log(f"RESTART {svc}: hung detected, restarting via NSSM")
    try:
        subprocess.run([NSSM, 'restart', svc], capture_output=True, timeout=30)
    except Exception as e:
        log(f"restart {svc} failed: {e}")


def main() -> int:
    log("hung-watchdog run")
    for svc, liveness_file, max_age in WATCH:
        state = _service_state(svc)
        if state != 'RUNNING':
            log(f"{svc}: state={state} (not running) - NSSM should handle; skip")
            continue
        age = _file_age_sec(DATA / liveness_file)
        if age > max_age:
            log(f"{svc}: RUNNING but liveness stale {age:.0f}s (> {max_age}s) = HUNG")
            _restart(svc)
        else:
            log(f"{svc}: healthy (liveness {age:.0f}s)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
