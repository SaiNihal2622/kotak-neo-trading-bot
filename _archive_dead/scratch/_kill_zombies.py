"""Kill orphan python.exe processes safely (NSSM python wrappers have empty cmdline)."""
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(".").resolve()
DCACHE = ROOT / "data_cache"


def get_active_bot_pid() -> int:
    liveness = json.loads((DCACHE / "liveness.json").read_text(encoding="utf-8"))
    return int(liveness.get("pid", 0))


def list_python_procs() -> list[dict]:
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" "
         "| Select-Object ProcessId, ParentProcessId, CreationDate, CommandLine "
         "| ConvertTo-Json -Compress"],
        capture_output=True, text=True
    )
    if not out.stdout.strip():
        return []
    data = json.loads(out.stdout)
    return data if isinstance(data, list) else [data]


def main():
    active_pid = get_active_bot_pid()
    print(f"Active trading bot pid: {active_pid}")

    procs = list_python_procs()
    print(f"\nFound {len(procs)} python.exe processes:\n")

    killed = []
    now = time.time()

    # Build allowlist: legitimate non-active-bot kotak processes by cmdline
    keep_cmdline_markers = [
        "kotak_bot",           # active bot + others
        "live_dashboard",      # dashboard
        "streamlit",           # streamlit dashboard
        "http_server",         # kotak http server
        "kite-mcp",            # kite MCP
        "watchdog",            # watchdog processes
        "supervisor",          # supervisor
        "self_heal",           # self-heal
    ]

    for p in procs:
        pid = int(p.get("ProcessId", 0))
        cmd = (p.get("CommandLine") or "").strip()
        parent = int(p.get("ParentProcessId", 0))
        creation_str = p.get("CreationDate", "")
        try:
            # Format: /Date(1700000000000+0000)/ or ISO
            if creation_str.startswith("/Date("):
                ms = int(creation_str[6:creation_str.index(")")])
                created = ms / 1000.0
            else:
                from datetime import datetime
                # Handle "20-09-2026 18:04:21" format
                created = datetime.strptime(creation_str, "%d-%m-%Y %H:%M:%S").timestamp()
            age_h = (now - created) / 3600
        except Exception:
            age_h = -1

        cmd_short = (cmd[:90] + "...") if len(cmd) > 90 else (cmd or "(empty)")

        # Decision
        if pid == active_pid:
            status = "ACTIVE BOT (keep)"
        elif cmd and any(m in cmd.lower() for m in keep_cmdline_markers):
            status = "legit (keep)"
        elif not cmd and age_h > 1.0:
            # Orphan: empty cmdline (NSSM wrapper), > 1h old, not the active bot
            kill = subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True, text=True
            )
            if kill.returncode == 0:
                killed.append(pid)
                status = "ORPHAN killed"
            else:
                status = f"ORPHAN (kill failed: {kill.stdout.strip()[:60]})"
        elif not cmd:
            status = f"empty-cmdline, {age_h:.1f}h old (skip — too recent)"
        else:
            status = "unrecognized cmdline (skip)"

        print(f"  PID {pid:6d} age={age_h:6.1f}h parent={parent:6d}  {status:35s} cmd='{cmd_short}'")

    print(f"\n{'='*60}")
    print(f"Active bot (kept):     {active_pid}")
    print(f"Orphans killed:        {len(killed)} ({killed})")


if __name__ == "__main__":
    main()