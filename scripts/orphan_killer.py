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


# FIX 2026-09-22 22:38: cache for the parent-map of all running python processes.
# Built once per orphan_killer run. Returns dict[pid, parent_pid].
_PARENT_MAP: dict[int, int] | None = None


def _build_parent_map() -> dict[int, int]:
    """Build {pid: parent_pid} for all python processes on the box.

    Uses PowerShell Get-CimInstance (same enum path as `_list_bot_processes`).
    Runs in the SYSTEM context (the orphan_killer is invoked from
    nssm_watchdog which is SYSTEM-elevated), so it sees every python process.
    """
    global _PARENT_MAP
    if _PARENT_MAP is not None:
        return _PARENT_MAP
    ps_cmd = (
        "Get-CimInstance Win32_Process -Filter \"Name like '%python%'\" "
        "| Select-Object ProcessId,ParentProcessId "
        "| ConvertTo-Csv -NoTypeInformation"
    )
    out: dict[int, int] = {}
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=20,
        )
        if r.returncode != 0 or not r.stdout:
            _log(f"  parent_map: powershell rc={r.returncode}")
            _PARENT_MAP = out
            return out
        import csv as _csv
        import io as _io
        reader = _csv.DictReader(_io.StringIO(r.stdout))
        for row in reader:
            try:
                pid = int((row.get("ProcessId") or "0").strip())
                ppid = int((row.get("ParentProcessId") or "0").strip())
            except Exception:
                continue
            if pid <= 0:
                continue
            out[pid] = ppid
    except Exception as e:
        _log(f"  parent_map: powershell failed: {e}")
    _PARENT_MAP = out
    return out


def _has_bot_descendant(pid: int) -> bool:
    """Return True if `pid` is the parent (or grandparent, etc.) of any other
    python process on the box.

    Used by the orphan-killer to avoid killing structural wrappers (e.g. the
    venv `py.exe` launcher that forwards I/O to the real `python.exe`). On
    Windows, killing the parent process cascades to the child — directly via
    job-object cleanup, or via SIGHUP-equivalent effects on the runtime —
    which in our setup took down the real bot every ~6 minutes.

    Walks the FULL process graph (not just the bot set) because the child
    might be a non-python python.exe whose parent process ID we still need
    to resolve.
    """
    pm = _build_parent_map()
    children_of: dict[int, list[int]] = {}
    for child_pid, parent_pid in pm.items():
        children_of.setdefault(parent_pid, []).append(child_pid)
    # BFS down from pid looking for any descendant that has a python child
    # or is itself a python process running the bot code.
    stack = [pid]
    seen = set()
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        for child in children_of.get(cur, []):
            if child in pm:
                # child is a python process — if its cmdline matches BOT_PATTERNS
                # we treat the original `pid` as a structural wrapper.
                if _is_bot_cmdline(_cmdline_for_pid(child)):
                    return True
            stack.append(child)
    return False


def _cmdline_for_pid(pid: int) -> str:
    """Return the commandline for a single python PID (via PowerShell)."""
    ps_cmd = (
        f"(Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\" "
        f"| Select-Object -First 1 -ExpandProperty CommandLine)"
    )
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=10,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


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

    # FIX 2026-09-22 22:38: NEVER kill a process that is the PARENT of any bot
    # process. On Windows, killing the parent process (e.g. via taskkill /F)
    # cascades to the child — either directly (job object cleanup, CTRL_BREAK
    # forwarding) or via SIGHUP-like effects on the runtime. The previous
    # 6-minute restart loop was caused by exactly this: the orphaned process
    # was the venv's `py.exe` launcher (which reads pyvenv.cfg and forwards
    # I/O to the real `python.exe`), and killing it took down the real bot too.
    # We now treat any bot process that has a bot child as "structural" — a
    # wrapper that exists solely to support another bot — and skip it.
    bot_pids = {p for p, _ in bots}
    _log(f"  parent map: {_build_parent_map()}")
    # FIX 2026-09-22 13:55: only kill an orphan if it's been alive for at least
    # MIN_ORPHAN_UPTIME_SEC. Without this, we were killing the new bot that
    # NSSM had JUST started (5s throttle means a fresh start is still in startup
    # phase when the 1-min watchdog fires), which then caused the old canonical
    # to die for unrelated reasons, then NSSM restarted again -> restart loop.
    # Now we wait 5 min of orphan uptime before declaring it killable.
    MIN_ORPHAN_UPTIME_SEC = 300
    for pid, cmdline in bots:
        if pid == canonical:
            _log(f"  PID {pid} matches paper.lock - KEEPING")
            continue
        # Skip if this orphan is the ancestor of any bot. Killing a parent bot
        # propagates to its children (the canonical bot is almost always one of
        # those children in this codebase, because of the venv py.exe launcher
        # pattern). The previous 6-min restart loop was this exact bug.
        if _has_bot_descendant(pid):
            _log(f"  PID {pid} is orphan but is the parent of another bot process (likely the py.exe launcher forwarding to the real python.exe) - LEAVING (structural wrapper)")
            continue
        # Orphan detected. Check its age via PowerShell (same enum pipeline).
        age_sec = _process_uptime_sec(pid)
        if age_sec is None:
            _log(f"  PID {pid} could not determine uptime, skipping (safer)")
            continue
        if age_sec < MIN_ORPHAN_UPTIME_SEC:
            _log(f"  PID {pid} is orphan but only {age_sec:.0f}s old (<{MIN_ORPHAN_UPTIME_SEC}s threshold) - LEAVING (likely mid-startup)")
            continue
        snippet = cmdline[:120].replace("\n", " ")
        _log(f"  ORPHAN: PID {pid} (uptime {age_sec/3600:.1f}h) does NOT match canonical {canonical}. cmdline={snippet}")
        if _kill(pid, "does_not_match_paper_lock"):
            killed_any = True

    return 1 if killed_any else 0


def _process_uptime_sec(pid: int) -> float | None:
    """Return the uptime of a PID in seconds, via PowerShell. None on error."""
    ps_cmd = f"(Get-Date) - (Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\").CreationDate | Select-Object -ExpandProperty TotalSeconds"
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0 or not r.stdout.strip():
            return None
        return float(r.stdout.strip())
    except Exception:
        return None


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        _log(f"FATAL: {e}")
        sys.exit(2)
