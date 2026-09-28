"""watchdog_restart.py - system-context watchdog for ancillary services.

FIX 2026-09-29 02:20 — addresses deferred issue #1 and #2 from
data_cache/session_handoff.md: confluence_loop and http_server :8502
were dying silently because:
  - http_server was registered as NSSM service but the service kept
    getting stuck in "Stopped" state (NSSM elevation issue, well-known)
  - confluence_loop was a bare Start-Process (PID 13620 etc.), not
    NSSM-managed at all

The watchdog:
  1. Probes http://127.0.0.1:8502/health — if DOWN, launches python
     in detached mode via Start-Process (which works from any context)
  2. Probes data_cache/_confluence_loop.heartbeat — if older than
     90s OR missing, launches confluence_loop.py in detached mode

Runs as SYSTEM-context scheduled task every 5 minutes. Self-restarts
both services when they die. Survives reboots (the scheduled task
itself has a logon trigger).

EXIT CODES
  0 - everything healthy (or restart succeeded)
  1 - both services healthy, no action needed
  2 - one or more restarts attempted
  3 - restart failed

USAGE
  python scripts/watchdog_restart.py            # run once
  python scripts/watchdog_restart.py --dry-run # check only, no restart
  python scripts/watchdog_restart.py --quiet   # suppress per-check logs
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

DATA = ROOT / "data_cache"
LOGS = ROOT / "Logs"
PY = ROOT / ".venv" / "Scripts" / "python.exe"

HEARTBEAT_PATH = DATA / "_confluence_loop.heartbeat"
HTTP_HEALTH_URL = "http://127.0.0.1:8502/health"
HEARTBEAT_STALE_SEC = 90  # confluence_loop writes every 30s, so 90s is "dead"
HTTP_TIMEOUT_SEC = 3


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _log(msg: str, quiet: bool) -> None:
    if not quiet:
        print(msg, flush=True)


def _is_http_alive() -> bool:
    """Return True if :8502 is responding to /health."""
    try:
        import httpx  # type: ignore
        r = httpx.get(HTTP_HEALTH_URL, timeout=HTTP_TIMEOUT_SEC)
        return r.status_code == 200
    except Exception:
        return False
    except BaseException:
        return False


def _restart_http_server(quiet: bool) -> tuple[bool, str]:
    """Launch kotak_bot.http_server on :8502 in detached mode."""
    out_log = LOGS / "http_server_watchdog.out"
    err_log = LOGS / "http_server_watchdog.err"
    out_log.parent.mkdir(parents=True, exist_ok=True)
    ps_script = (
        f"$p = Start-Process -FilePath '{PY}' "
        f"-ArgumentList @('-u', '-m', 'kotak_bot.http_server', '--port', '8502') "
        f"-WorkingDirectory '{ROOT}' "
        f"-RedirectStandardOutput '{out_log}' "
        f"-RedirectStandardError '{err_log}' "
        f"-WindowStyle Hidden -PassThru; "
        f"Write-Output $p.Id"
    )
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
            capture_output=True, text=True, timeout=15,
        )
        if proc.returncode != 0:
            return False, f"powershell rc={proc.returncode}: {proc.stderr.strip()[:200]}"
        pid_line = proc.stdout.strip().splitlines()[-1]
        pid = int(pid_line.strip())
        return True, f"launched PID {pid}"
    except Exception as e:
        return False, f"exception: {e}"


def _heartbeat_age_sec() -> float | None:
    """Return seconds since the confluence_loop heartbeat was last written, or None if missing."""
    if not HEARTBEAT_PATH.exists():
        return None
    try:
        return time.time() - HEARTBEAT_PATH.stat().st_mtime
    except Exception:
        return None


def _is_confluence_alive() -> bool:
    age = _heartbeat_age_sec()
    if age is None:
        return False
    return age < HEARTBEAT_STALE_SEC


def _restart_confluence_loop(quiet: bool) -> tuple[bool, str]:
    """Launch _confluence_loop.py in detached mode."""
    out_log = LOGS / "confluence_loop_watchdog.out"
    err_log = LOGS / "confluence_loop_watchdog.err"
    out_log.parent.mkdir(parents=True, exist_ok=True)
    ps_script = (
        f"$p = Start-Process -FilePath '{PY}' "
        f"-ArgumentList @('scripts/_confluence_loop.py') "
        f"-WorkingDirectory '{ROOT}' "
        f"-RedirectStandardOutput '{out_log}' "
        f"-RedirectStandardError '{err_log}' "
        f"-WindowStyle Hidden -PassThru; "
        f"Write-Output $p.Id"
    )
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
            capture_output=True, text=True, timeout=15,
        )
        if proc.returncode != 0:
            return False, f"powershell rc={proc.returncode}: {proc.stderr.strip()[:200]}"
        pid_line = proc.stdout.strip().splitlines()[-1]
        pid = int(pid_line.strip())
        return True, f"launched PID {pid}"
    except Exception as e:
        return False, f"exception: {e}"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="check only, no restart")
    p.add_argument("--quiet", action="store_true", help="suppress per-check logs")
    args = p.parse_args()

    http_alive = _is_http_alive()
    conf_age = _heartbeat_age_sec()
    conf_alive = conf_age is not None and conf_age < HEARTBEAT_STALE_SEC
    conf_desc = (
        f"alive (age={conf_age:.0f}s)" if conf_alive
        else f"DEAD (age={'?' if conf_age is None else f'{conf_age:.0f}s'})"
    )
    http_desc = "alive" if http_alive else "DEAD"
    _log(f"[watchdog] http_server :8502 = {http_desc}", args.quiet)
    _log(f"[watchdog] confluence_loop     = {conf_desc}", args.quiet)

    if http_alive and conf_alive:
        return 0  # healthy, nothing to do

    if args.dry_run:
        _log("[watchdog] dry-run: would restart dead services", args.quiet)
        return 1

    restarts = []
    if not http_alive:
        ok, msg = _restart_http_server(args.quiet)
        restarts.append(("http_server", ok, msg))
        if ok:
            time.sleep(3.0)
    if not conf_alive:
        ok, msg = _restart_confluence_loop(args.quiet)
        restarts.append(("confluence_loop", ok, msg))

    failed = [name for name, ok, _ in restarts if not ok]
    if failed:
        _log(f"[watchdog] RESTART FAILED for: {','.join(failed)}", args.quiet)
        for name, ok, msg in restarts:
            _log(f"  {name}: {'OK' if ok else 'FAIL'} {msg}", args.quiet)
        return 3

    # Write a marker file so external monitors see the watchdog ran
    try:
        marker = DATA / "_watchdog_restart.json"
        marker.write_text(json.dumps({
            "ts": _now_iso(),
            "restarts": [{"name": n, "ok": ok, "msg": m} for n, ok, m in restarts],
        }, indent=2), encoding="utf-8")
    except Exception:
        pass
    _log(f"[watchdog] restarted: {[name for name, _, _ in restarts]}", args.quiet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
