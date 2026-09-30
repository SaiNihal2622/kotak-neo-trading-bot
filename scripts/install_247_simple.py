"""Install NSSM services — SIMPLIFIED single-line per service.

PHASE 6 FIX 2026-09-30 v2: the original install_247_services.py failed when
run via the SYSTEM-context bot because it used NSSM's `set` command in
many separate subprocess calls, and one of those calls (`set ... AppEnvironmentExtra`
with a multi-line value containing null bytes) triggered a "Can't open
service" error.

This simpler version:
1. Calls `nssm install <name> <exe> <args>` ONCE per service.
2. Calls `nssm set` for the simple, single-value params (no env block).
3. Calls `nssm start` to launch.
4. Logs every step to data_cache/install_247_log.txt for debugging.

Usage:
    python scripts/install_247_simple.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
NSSM = Path(r"C:\Tools\nssm\nssm-2.24\win64\nssm.exe")
LOG_FILE = PROJECT_ROOT / "data_cache" / "install_247_log.txt"
PYTHON_EXE = str(PROJECT_ROOT / ".venv" / "Scripts" / "python.exe")

IST = timezone(timedelta(hours=5, minutes=30))

# (name, module, args_str)
SERVICES = [
    ("KotakCoreAPI",     "system.core.api.server",      '--db data_cache\\state.db --port 8510'),
    ("KotakBrainBridge", "system.bridge.brain_bridge",  '--interval 5'),
    ("KotakBrainDaemon", "system.brain.brain_daemon",  '--interval 120'),
    ("KotakExecGateway", "system.exec.exec_gateway",   '--live'),
]


def log(msg: str) -> None:
    """Append to log file + print."""
    line = f"[{datetime.now(IST).isoformat()}] {msg}"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    print(line, flush=True)


def run(cmd: list[str]) -> tuple[int, str, str]:
    """Run subprocess; return (rc, stdout, stderr)."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        return p.returncode, p.stdout, p.stderr
    except Exception as e:
        return -1, "", str(e)


def install(name: str, module: str, args_str: str) -> bool:
    log(f"[install] {name} module={module} args={args_str}")

    # nssm install <name> <exe> <args>
    rc, out, err = run([str(NSSM), "install", name, PYTHON_EXE, f"-u -m {module} {args_str}"])
    if rc != 0:
        if "already exists" in (out + err).lower():
            log(f"  service already registered — proceeding to configure")
        else:
            log(f"  ! install failed rc={rc}: {(out+err).strip()[:200]}")
            return False
    else:
        log(f"  service registered")

    # nssm set <name> AppDirectory <path>
    rc, _, err = run([str(NSSM), "set", name, "AppDirectory", str(PROJECT_ROOT)])
    log(f"  AppDirectory rc={rc}" + (f" err={err.strip()[:100]}" if rc else ""))

    # nssm set <name> AppStdout <log>
    rc, _, err = run([str(NSSM), "set", name, "AppStdout", str(PROJECT_ROOT / "Logs" / f"{name}.out.log")])
    log(f"  AppStdout rc={rc}" + (f" err={err.strip()[:100]}" if rc else ""))

    rc, _, err = run([str(NSSM), "set", name, "AppStderr", str(PROJECT_ROOT / "Logs" / f"{name}.err.log")])
    log(f"  AppStderr rc={rc}" + (f" err={err.strip()[:100]}" if rc else ""))

    # nssm set <name> AppRotateFiles 1
    rc, _, err = run([str(NSSM), "set", name, "AppRotateFiles", "1"])
    log(f"  AppRotateFiles rc={rc}" + (f" err={err.strip()[:100]}" if rc else ""))

    rc, _, err = run([str(NSSM), "set", name, "AppRotateBytes", "10485760"])
    log(f"  AppRotateBytes rc={rc}" + (f" err={err.strip()[:100]}" if rc else ""))

    # nssm set <name> AppExit Default Restart
    rc, _, err = run([str(NSSM), "set", name, "AppExit", "Default", "Restart"])
    log(f"  AppExit Restart rc={rc}" + (f" err={err.strip()[:100]}" if rc else ""))

    rc, _, err = run([str(NSSM), "set", name, "AppRestartDelay", "5000"])
    log(f"  AppRestartDelay rc={rc}" + (f" err={err.strip()[:100]}" if rc else ""))

    rc, _, err = run([str(NSSM), "set", name, "AppNoConsole", "1"])
    log(f"  AppNoConsole rc={rc}" + (f" err={err.strip()[:100]}" if rc else ""))

    # DisplayName + Start type
    rc, _, err = run([str(NSSM), "set", name, "DisplayName", name])
    log(f"  DisplayName rc={rc}" + (f" err={err.strip()[:100]}" if rc else ""))

    rc, _, err = run([str(NSSM), "set", name, "Start", "SERVICE_AUTO_START"])
    log(f"  AutoStart rc={rc}" + (f" err={err.strip()[:100]}" if rc else ""))

    # PYTHONIOENCODING for utf-8 output (the bot log shows garbled chars otherwise)
    rc, _, err = run([str(NSSM), "set", name, "AppEnvironmentExtra", "PYTHONIOENCODING=utf-8\x00KOTAK_STALE_ORDER_SEC=3600"])
    log(f"  AppEnvironmentExtra rc={rc}" + (f" err={err.strip()[:100]}" if rc else ""))

    # nssm start
    rc, out, err = run([str(NSSM), "start", name])
    if rc == 0:
        log(f"  ✓ STARTED")
        return True
    elif rc == 1056:  # already running
        log(f"  already running")
        return True
    else:
        log(f"  ! start failed rc={rc}: {(out+err).strip()[:200]}")
        return False


def main() -> int:
    if not NSSM.exists():
        log(f"!! nssm not found at {NSSM}")
        return 2

    (PROJECT_ROOT / "Logs").mkdir(parents=True, exist_ok=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    ok = 0
    for name, module, args_str in SERVICES:
        if install(name, module, args_str):
            ok += 1

    # Final status
    log(f"\n=== Done. {ok}/{len(SERVICES)} services installed/started ===")
    log("Verify: nssm status <name>\n")
    return 0 if ok == len(SERVICES) else 1


if __name__ == "__main__":
    sys.exit(main())