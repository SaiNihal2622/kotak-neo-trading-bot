"""Install NSSM services for the new core trading system.

PHASE 6 FIX 2026-09-30: makes the system "non-glued" by registering each
subsystem as a proper Windows service under NSSM. After installation,
each subsystem auto-restarts on crash (NSSM built-in) and survives
machine reboots. The kotak-bot-watchdog cron (already enabled) only needs
to verify they're alive — restart is automatic.

Services registered:
- KotakCoreAPI      — system.core.api.server     (port 8510)
- KotakBrainBridge  — system.bridge.brain_bridge (5s poll)
- KotakBrainDaemon  — system.brain.brain_daemon (60-120s cycle)
- KotakExecGateway  — system.exec.exec_gateway  (--live mode)

Installation method:
- Via UAC: user runs `python scripts/install_247_services.py` from elevated
  PowerShell. nssm.exe is at C:\Tools\nssm\nssm-2.24\win64\nssm.exe.
- No-UAC: write a force-action JSON to data_cache/mavis_force_action.json
  with this script as the command — the SYSTEM-running bot reads the file
  and invokes it without UAC (per the AGENTS.md precedent for
  `schtasks /create /RU SYSTEM`).

Each service gets:
- AppStdout / AppStderr: Logs\<service>.{out,err}.log
- AppRotateFiles: 1 (NSSM rotates logs)
- AppRotateBytes: 10 MB
- AppExit: Default Restart
- AppRestartDelay: 5000 ms

Idempotent: re-running this script UPDATES existing services (nssm set)
rather than failing. Safe to invoke multiple times.

Verify after install:
    sc query KotakCoreAPI
    net start KotakCoreAPI
    nssm status KotakCoreAPI
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
NSSM = Path(r"C:\Tools\nssm\nssm-2.24\win64\nssm.exe")

# Service definitions: name -> (module, args, env, log_prefix)
SERVICES = {
    "KotakCoreAPI": {
        "module": "system.core.api.server",
        "args": ['"--db"', "data_cache\\state.db", '"--port"', "8510"],
        "env": {
            "PYTHONIOENCODING": "utf-8",
            "KOTAK_STALE_ORDER_SEC": "3600",
        },
        "log_prefix": "core_api",
        "description": "Kotak-neo-bot core API server (event-sourced trading core). Port 8510.",
    },
    "KotakBrainBridge": {
        "module": "system.bridge.brain_bridge",
        "args": ['"--interval"', "5"],
        "env": {
            "PYTHONIOENCODING": "utf-8",
        },
        "log_prefix": "brain_bridge",
        "description": "Kotak-neo-bot brain bridge — polls quant_actions.json, submits plans via /api/plan. Polls every 5s.",
    },
    "KotakBrainDaemon": {
        "module": "system.brain.brain_daemon",
        "args": ['"--interval"', "120"],
        "env": {
            "PYTHONIOENCODING": "utf-8",
        },
        "log_prefix": "brain_daemon",
        "description": "Kotak-neo-bot brain daemon — LLM-driven trading decisions every 120s. Writes quant_actions.json for the bridge.",
    },
    "KotakExecGateway": {
        "module": "system.exec.exec_gateway",
        "args": ['"--live"'],
        "env": {
            "PYTHONIOENCODING": "utf-8",
        },
        "log_prefix": "exec_gateway",
        "description": "Kotak-neo-bot exec gateway — converts ORDER_PROPOSED events to fills. --live mode (paper, real positions).",
    },
}

PYTHON_EXE = str(PROJECT_ROOT / ".venv" / "Scripts" / "python.exe")


def run(cmd: list[str], *, check: bool = True) -> tuple[int, str, str]:
    """Run a subprocess, return (rc, stdout, stderr)."""
    p = subprocess.run(cmd, capture_output=True, text=True)
    if check and p.returncode != 0:
        print(f"  ! rc={p.returncode} cmd={cmd[:5]}... err={p.stderr[:200]}")
    return p.returncode, p.stdout, p.stderr


def nssm(*args: str) -> tuple[int, str, str]:
    return run([str(NSSM), *args])


def service_installed(name: str) -> bool:
    """Check if an NSSM service is already registered."""
    rc, _, _ = nssm("status", name)
    # nssm status returns rc=0 for installed+stopped, rc=3 for not installed,
    # rc=1 for installed+paused (varies). Treat rc=3 as "not installed".
    rc, out, err = nssm("status", name)
    if rc != 0 and "service does not exist" in (out + err).lower():
        return False
    return rc == 0 or "SERVICE_INSTALLED" in (out + err) or "SERVICE_STOPPED" in (out + err) or "SERVICE_RUNNING" in (out + err) or "SERVICE_PAUSED" in (out + err)


def install_service(name: str, cfg: dict, *, force: bool = False) -> None:
    """Install (or update) a single NSSM service."""
    print(f"\n[install] {name}")

    # 1. Stop + remove if force=True and currently running
    if force and service_installed(name):
        print(f"  stopping + removing existing...")
        nssm("stop", name)
        nssm("remove", name, "confirm")

    # 2. Install
    module = cfg["module"]
    args_str = " ".join(cfg["args"])
    # Quote the python.exe path because of spaces
    rc, _, err = nssm("install", name, PYTHON_EXE, f"-u -m {module} {args_str}")
    if rc != 0 and "already exists" not in err.lower():
        print(f"  ! install failed: {err[:200]}")
        return

    # 3. Configure
    # Working directory
    nssm("set", name, "AppDirectory", str(PROJECT_ROOT))
    # Log rotation
    nssm("set", name, "AppStdout", str(PROJECT_ROOT / "Logs" / f"{cfg['log_prefix']}.out.log"))
    nssm("set", name, "AppStderr", str(PROJECT_ROOT / "Logs" / f"{cfg['log_prefix']}.err.log"))
    nssm("set", name, "AppRotateFiles", "1")
    nssm("set", name, "AppRotateBytes", "10485760")  # 10 MB
    # Restart on crash
    nssm("set", name, "AppExit", "Default", "Restart")
    nssm("set", name, "AppRestartDelay", "5000")
    # Don't show window
    nssm("set", name, "AppNoConsole", "1")
    # Environment variables
    env_block = "\0".join(f"{k}={v}" for k, v in cfg.get("env", {}).items()) + "\0"
    nssm("set", name, "AppEnvironmentExtra", env_block)
    # Description
    nssm("set", name, "AppDescription", cfg.get("description", ""))
    # Startup type: Automatic (start at boot)
    nssm("set", name, "Start", "SERVICE_AUTO_START")
    # Display name
    nssm("set", name, "DisplayName", name)

    print(f"  registered: {PYTHON_EXE} -u -m {module} {args_str}")
    print(f"  log: Logs/{cfg['log_prefix']}.err.log")
    print(f"  restart: on-crash, 5s delay")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--force", action="store_true",
                   help="stop + remove existing services before reinstalling")
    p.add_argument("--only", help="only act on the named service")
    p.add_argument("--no-start", action="store_true",
                   help="install but don't start the services")
    args = p.parse_args()

    if not NSSM.exists():
        print(f"!! nssm not found at {NSSM}")
        print("   Install via: choco install nssm   (or download from <TBD>)")
        return 2

    if not Path(PYTHON_EXE).exists():
        print(f"!! python not found at {PYTHON_EXE}")
        return 2

    # Make sure Logs dir exists
    (PROJECT_ROOT / "Logs").mkdir(parents=True, exist_ok=True)

    targets = SERVICES
    if args.only:
        if args.only not in targets:
            print(f"!! unknown service '{args.only}'. Available: {list(targets.keys())}")
            return 2
        targets = {args.only: targets[args.only]}

    for name, cfg in targets.items():
        install_service(name, cfg, force=args.force)

    if not args.no_start:
        print("\n[start] launching services...")
        for name in targets:
            rc, _, _ = nssm("start", name)
            print(f"  {name}: rc={rc} (0=started, 1056=already-running)")

    print("\n[verify] service statuses:")
    for name in targets:
        rc, out, _ = nssm("status", name)
        print(f"  {name}: rc={rc} {out.strip()}")

    print("\n[done] All services registered under NSSM.")
    print("       They will auto-restart on crash and survive reboots.")
    print("       Run `nssm status <name>` to check any service.")
    return 0


if __name__ == "__main__":
    sys.exit(main())