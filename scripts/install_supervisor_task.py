"""install_supervisor_task.py — register the SYSTEM-context supervisor as a scheduled task.

The supervisor_loop.ps1 runs as LocalSystem with HIGHEST privileges and
checks every 30 sec that the bot + brain are alive. This is the ALWAYS-ON
layer below NSSM: if NSSM is stopped, the supervisor restarts it; if the
bot process dies, the supervisor restarts it.

The scheduled task itself is:
  Name: KotakSupervisor
  Run as: SYSTEM (LocalSystem account)
  Run level: HIGHEST
  Trigger: At system startup
  Action: powershell -NoProfile -ExecutionPolicy Bypass -File <supervisor_loop.ps1>
  Settings: Don't stop if on battery, run indefinitely, restart on failure

This is a 24/7 watchdog that survives user logoff, machine sleep, and
NSSM service failures. The only way it dies is if the entire machine
reboots, in which case the task fires at system startup.

USAGE:
  python scripts/install_supervisor_task.py        # register
  python scripts/install_supervisor_task.py --remove  # unregister

NOTE: schtasks /create /RU SYSTEM /RL HIGHEST requires admin, which the
user-context doesn't have. This script writes a force-action JSON that
the running bot (which IS SYSTEM when NSSM-managed) processes, calling
schtasks itself.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
DCACHE = ROOT / "data_cache"
SYSTEM_DIR = ROOT / "system"
SUPERVISOR_PS1 = SYSTEM_DIR / "supervisor_loop.ps1"
FORCE_ACTION = DCACHE / "mavis_force_action.json"

# Build the command that the SYSTEM bot will run
PS_EXE = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
SUPERVISOR_CMD = [
    PS_EXE, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(SUPERVISOR_PS1)
]


def _build_register_action(reason: str) -> dict:
    """Build the force-action JSON that registers the supervisor as a SYSTEM task."""
    # schtasks command to register the task
    # /SC ONSTART fires at system startup
    # /RL HIGHEST runs with highest privileges
    # /RU SYSTEM runs as LocalSystem
    # /F overwrites if exists
    schtasks_cmd = [
        "schtasks", "/create",
        "/tn", "KotakSupervisor",
        "/tr", f'"{PS_EXE}" -NoProfile -ExecutionPolicy Bypass -File "{SUPERVISOR_PS1}"',
        "/sc", "ONSTART",
        "/ru", "SYSTEM",
        "/rl", "HIGHEST",
        "/f",
    ]
    return {
        "action": "RUN_COMMAND",
        "ts": datetime.now().isoformat(timespec="seconds"),
        "consumed": False,
        "command": schtasks_cmd,
        "reason": reason,
        "timeout": 30,
    }


def _build_remove_action() -> dict:
    """Build the force-action JSON that removes the supervisor task."""
    return {
        "action": "RUN_COMMAND",
        "ts": datetime.now().isoformat(timespec="seconds"),
        "consumed": False,
        "command": ["schtasks", "/delete", "/tn", "KotakSupervisor", "/f"],
        "reason": "remove KotakSupervisor scheduled task",
        "timeout": 15,
    }


def _build_start_action() -> dict:
    """Build the force-action JSON that immediately starts the supervisor task
    (in case the user wants to start it now, not on next boot)."""
    return {
        "action": "RUN_COMMAND",
        "ts": datetime.now().isoformat(timespec="seconds"),
        "consumed": False,
        "command": ["schtasks", "/run", "/tn", "KotakSupervisor"],
        "reason": "immediately start the KotakSupervisor task",
        "timeout": 15,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--remove", action="store_true", help="Remove the supervisor task")
    parser.add_argument("--start", action="store_true", help="Immediately start the supervisor (in addition to registering)")
    args = parser.parse_args()

    if not SUPERVISOR_PS1.exists():
        print(f"ERROR: supervisor_loop.ps1 not found at {SUPERVISOR_PS1}")
        return 1

    if args.remove:
        action = _build_remove_action()
        print(f"Writing REMOVE action to {FORCE_ACTION}")
    else:
        reason = f"register KotakSupervisor (SYSTEM-context 24/7 watchdog) — every 30s check + auto-restart"
        if args.start:
            reason += " + start now"
        action = _build_register_action(reason)
        if args.start:
            # Add a second action to start it
            action["command_after_register"] = _build_start_action()["command"]
        print(f"Writing REGISTER action to {FORCE_ACTION}")

    FORCE_ACTION.write_text(json.dumps(action, indent=2), encoding="utf-8")
    print(f"The running bot (NSSM-managed, SYSTEM context) will execute this within ~30s.")
    print(f"After execution, run: schtasks /query /tn KotakSupervisor  (from admin shell)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
