"""Orphan bot killer.

Background:
  The user hit a recurring issue (2026-09-22 13:30) where an old bot process
  (PID 11204, 19h58m uptime) survived an NSSM restart. It kept writing to
  liveness.json with stale data while the new bot (PID 4132) wrote its own
  data to paper.lock. The result: two bots racing, reconcile mismatched,
  HTTP :8502/health returned wrong PID.

  NSSM's "stop" should have killed PID 11204 but didn't (likely a UAC
  split-token issue when Restart-Service is invoked from user context).
  This script provides a 4th-layer safety net: periodically enumerate all
  python processes, identify which ones are running the kotak_bot trading
  loop, and kill any whose PID does NOT match paper.lock.

How it runs:
  - Invoked by scripts/nssm_watchdog.py every 15 min via the
    kotak-nssm-watchdog scheduled task (which already runs as SYSTEM
    with HIGHEST elevation, bypassing the UAC issue).
  - Also callable directly: python scripts/_orphan_killer.py

Exit codes:
  0 = no orphans (clean)
  1 = one or more orphans killed
  2 = script error

Implementation note:
  We use wmic (built into Windows) to enumerate processes because it works
  from SYSTEM context without requiring psutil on the SYSTEM Python path.
  psutil works from user context but cannot read SYSTEM-process cmdlines
  (AccessDenied). wmic has no such restriction when run as SYSTEM.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.resolve()
LOG = ROOT / "Logs" / "orphan_killer.log"
DCACHE = ROOT / "data_cache"

# What cmdline patterns identify a "kotak_bot trading loop" process.
# We INTENTIONALLY only match the trading loop (`-m kotak_bot paper`), NOT:
#   - kotak_bot.http_server (the :8502 dashboard API; killing it breaks the UI)
#   - quant_service.py (the brain; killing it kills :8503 and the in-process scheduler)
#   - crypto_options_bot (a separate project the user also runs)
# Only the trading loop competes for paper.lock / paper_state.json, so only
# the trading loop needs orphan management. The HTTP server and brain each
# have their own NSSM services and don't race against each other.
BOT_PATTERNS = (
    "-m kotak_bot paper",
    "kotak_bot\\__main__",
)


def _log(msg: str) -> None:
    line = f"[{datetime.now().isoformat()}] {msg}"
    print(line)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _read_lock_pid() -> int | None:
    lock_path = DCACHE / "paper.lock"
    if not lock_path.exists():
        return None
    try:
        text = lock_path.read_text(encoding="utf-8").strip()
        if not text:
            return None
        return int(text.split()[0])
    except Exception as e:
        _log(f"  could not parse paper.lock: {e}")
        return None


def _list_bot_processes() -> list[tuple[int, str]]:
    """Return list of (pid, cmdline) for processes whose cmdline matches BOT_PATTERNS.

    Uses PowerShell's Get-CimInstance Win32_Process to enumerate python
    processes. This works on every Windows version including Win11 24H2+
    where wmic has been deprecated. Works from SYSTEM context without
    needing psutil.
    """
    out: list[tuple[int, str]] = []
    # PowerShell pipeline: filter to python*, select ProcessId+CommandLine,
    # output as CSV. Use single-quoted here-string to avoid escaping issues.
    ps_cmd = (
        "Get-CimInstance Win32_Process -Filter \"Name like '%python%'\" "
        "| Select-Object ProcessId,CommandLine "
        "| ConvertTo-Csv -NoTypeInformation"
    )
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=20,
        )
    except Exception as e:
        _log(f"  powershell.exe failed: {e}")
        return out

    if r.returncode != 0 or not r.stdout:
        _log(f"  PowerShell rc={r.returncode} stderr={r.stderr.strip()[:300]}")
        return out

    import csv as _csv
    import io as _io
    reader = _csv.DictReader(_io.StringIO(r.stdout))
    for row in reader:
        try:
            pid = int((row.get("ProcessId") or "0").strip())
            cmd = (row.get("CommandLine") or "").strip()
        except Exception:
            continue
        if pid <= 0:
            continue
        out.append((pid, cmd))

    return out


def _is_bot_cmdline(cmdline: str) -> bool:
    cl = cmdline.lower()
    return any(p.lower() in cl for p in BOT_PATTERNS)


def _kill(pid: int, reason: str) -> bool:
    """Kill a process by PID via taskkill /F (works from SYSTEM context)."""
    try:
        r = subprocess.run(
            ["taskkill", "/F", "/PID", str(pid)],
            capture_output=True, text=True, timeout=10,
        )
        ok = r.returncode == 0
        _log(f"  taskkill /F /PID {pid} exit={r.returncode} reason={reason} ok={ok}")
        _log(f"    stdout={r.stdout.strip()[:200]} stderr={r.stderr.strip()[:200]}")
        return ok
    except Exception as e:
        _log(f"  taskkill failed for PID {pid}: {e}")
        return False


def main() -> int:
    _log(f"=== orphan_killer run ===")
    canonical = _read_lock_pid()
    if canonical is None:
        _log("  paper.lock missing or empty - bot may not be running. Skipping.")
        return 0
    _log(f"  canonical bot PID (from paper.lock): {canonical}")

    candidates = _list_bot_processes()
    bots = [(pid, cmd) for pid, cmd in candidates if _is_bot_cmdline(cmd)]

    if not candidates:
        _log("  wmic returned no python processes at all.")
    if not bots:
        _log("  no bot cmdlines matched BOT_PATTERNS. (candidates=" +
             str(len(candidates)) + ")")
    if not bots:
        return 0

    _log(f"  found {len(bots)} bot process(es): PIDs={[p for p, _ in bots]}")

    killed_any = False
    for pid, cmdline in bots:
        if pid == canonical:
            _log(f"  PID {pid} matches paper.lock - KEEPING")
            continue
        # Orphan detected - kill it
        snippet = cmdline[:120].replace("\n", " ")
        _log(f"  ORPHAN: PID {pid} does NOT match canonical {canonical}. cmdline={snippet}")
        if _kill(pid, "does_not_match_paper_lock"):
            killed_any = True

    return 1 if killed_any else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        _log(f"FATAL: {e}")
        sys.exit(2)
