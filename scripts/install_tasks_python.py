"""install_tasks_python.py - reliable admin installer using ctypes + COM.

FIX 2026-09-04 15:25: the PowerShell install_daily_tasks.ps1 was failing because:
1. The script exits before the elevated PowerShell window shows output
2. UAC dialogs don't complete the install
3. Arguments were concatenated wrong

This Python script:
1. Detects if running as admin
2. If not, self-elevates via ShellExecuteEx with lpVerb='runas'
3. After elevation, uses the scheduler COM API to register tasks
4. Outputs clear results

Usage: just run this script as Administrator. Or double-click install_tasks_python.bat
"""
import ctypes
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
LOG = ROOT / "Logs" / "install_tasks.log"
LOG.parent.mkdir(parents=True, exist_ok=True)


def log(msg):
    line = f"[{__import__('datetime').datetime.now().isoformat()}] {msg}"
    print(line)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def is_admin():
    """Check if running as admin."""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def self_elevate():
    """Re-launch this script with admin privileges via ShellExecuteW + runas verb."""
    SW_SHOWNORMAL = 1
    script_path = os.path.abspath(__file__)
    args = " ".join([f'"{a}"' if " " in a else a for a in sys.argv[1:]])
    # Build the command: python.exe "C:\path\to\script.py" args...
    cmd = f'"{sys.executable}" "{script_path}" {args}'
    log(f"elevating: {cmd}")
    try:
        rc = ctypes.windll.shell32.ShellExecuteW(
            None,           # hwnd
            "runas",        # lpOperation
            cmd,            # lpFile (with params)
            None,           # lpParameters
            None,           # lpDirectory
            SW_SHOWNORMAL   # nShowCmd
        )
        log(f"ShellExecuteW returned: {rc} (>32 = success)")
    except Exception as e:
        log(f"ShellExecuteW error: {e}")
    sys.exit(0)


def create_task_via_schtasks(name, time_str, args):
    """Create a scheduled task using schtasks.exe (more reliable than PowerShell)."""
    cmd = [
        "schtasks", "/create",
        "/tn", name,
        "/tr", f'C:\\Users\\saini\\.minimax-agent\\projects\\kotak-neo-bot\\.venv\\Scripts\\python.exe "C:\\Users\\saini\\.minimax-agent\\projects\\kotak-neo-bot\\scripts\\daily_autonomy.py" {args}',
        "/sc", "daily",
        "/st", time_str,
        "/rl", "highest",
        "/f",  # force overwrite
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15, shell=True)
        return result.returncode == 0, result.stdout + result.stderr
    except Exception as e:
        return False, str(e)


def main():
    if not is_admin():
        log("Not running as admin. Requesting elevation...")
        log("USER ACTION: Click YES on the UAC dialog that just appeared")
        self_elevate()
        return  # not reached

    log("=" * 60)
    log("Running as Administrator. Installing daily tasks.")
    log("=" * 60)

    tasks = [
        ("kotak-pre-market-self-heal", "08:25", "pre_market"),
        ("kotak-eod-pnl-evaluator", "15:30", "eod"),
        ("kotak-nightly-state-backup", "23:00", "nightly"),
    ]

    for name, time_str, args in tasks:
        log(f"installing {name} at {time_str} IST...")
        ok, msg = create_task_via_schtasks(name, time_str, args)
        if ok:
            log(f"  SUCCESS: {name}")
        else:
            log(f"  FAILED: {name}: {msg[:200]}")

    log("=" * 60)
    log("Verification:")
    result = subprocess.run(["schtasks", "/query", "/fo", "list"],
                          capture_output=True, text=True, timeout=15, shell=True)
    for line in result.stdout.splitlines():
        if "kotak-" in line.lower():
            log(f"  {line}")
    log("=" * 60)
    log("Done. Press Enter to close.")
    try:
        input()
    except EOFError:
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"FATAL: {e}")
        try:
            input()
        except EOFError:
            pass
