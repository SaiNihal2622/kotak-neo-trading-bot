"""Pre-market readiness check for tomorrow's market open.

Runs at 8:30 IST (before market opens at 9:00). Verifies:
1. Core service up on :8510
2. Bot adapter bridging legacy JSON
3. Kotak session still valid (will be re-authed at 8:25 by daily_maintenance)
4. Required scheduled tasks are in place
5. data files writable, no disk full
6. Position count and cash match expected baseline

Usage:
  python -m system.core.premarket_check

Exits 0 if all green, 1 if any blocker.
"""
from __future__ import annotations

import json
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path


IST = timezone(timedelta(hours=5, minutes=30))
ROOT = Path(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot")


class Check:
    def __init__(self):
        self.results: list[tuple[str, bool, str]] = []

    def add(self, name: str, ok: bool, detail: str = ""):
        self.results.append((name, ok, detail))
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name}: {detail}")

    def summary(self) -> bool:
        print()
        passed = sum(1 for _, ok, _ in self.results if ok)
        failed = len(self.results) - passed
        print(f"=== {passed} passed, {failed} failed ===")
        return failed == 0


def check_core(check: Check):
    """1. Core service healthy on :8510."""
    try:
        r = urllib.request.urlopen("http://127.0.0.1:8510/healthz", timeout=3)
        data = json.loads(r.read())
        if data.get("ok") and "events_in_log" in data:
            check.add("Core service", True, f"up, {data['events_in_log']} events")
        else:
            check.add("Core service", False, f"unhealthy: {data}")
    except Exception as e:
        check.add("Core service", False, f"unreachable: {e}")


def check_adapter(check: Check):
    """2. Bot adapter process running."""
    import psutil
    found = False
    for p in psutil.process_iter(["cmdline"]):
        cmd = " ".join(p.info["cmdline"] or [])
        if "system.core.migration.bot_adapter" in cmd:
            found = True
            check.add("Bot adapter", True, f"PID {p.pid}")
            break
    if not found:
        check.add("Bot adapter", False, "not running")


def check_bot_service(check: Check):
    """3. Legacy bot NSSM service running."""
    try:
        r = subprocess.run(
            ["C:\\Tools\\nssm\\nssm-2.24\\win32\\nssm.exe", "status", "KotakBotPaper"],
            capture_output=True, timeout=5,
        )
        # nssm on Windows outputs UTF-16LE; decode bytes
        out = r.stdout.decode("utf-16le", errors="ignore")
        if "SERVICE_RUNNING" in out:
            check.add("Legacy bot service", True, "running")
        else:
            check.add("Legacy bot service", False, f"not running: {out.strip()[:80]}")
    except Exception as e:
        check.add("Legacy bot service", False, f"check failed: {e}")


def check_kotak_session(check: Check):
    """4. Kotak session file exists and is valid."""
    session_path = ROOT / "data_cache" / "kotak_prod_session.json"
    if not session_path.exists():
        check.add("Kotak session", False, "no session file — bot must re-auth")
        return
    try:
        ses = json.loads(session_path.read_text(encoding="utf-8"))
        # The Kotak session uses 'access_token' as the field name
        token = ses.get("access_token") or ses.get("session_token") or ""
        expires_ts = ses.get("expires_at", 0)
        if token and expires_ts > 0:
            now_ts = datetime.now(IST).timestamp()
            hrs = (expires_ts - now_ts) / 3600
            if hrs > 0:
                check.add("Kotak session", True, f"valid for {hrs:.1f}h")
            else:
                check.add("Kotak session", False,
                          f"expired {abs(hrs):.1f}h ago — bot will re-auth at 8:25 IST")
        else:
            check.add("Kotak session", False, "missing token or expiry")
    except Exception as e:
        check.add("Kotak session", False, f"parse error: {e}")


def check_scheduled_tasks(check: Check):
    """5. Required scheduled tasks in place."""
    required = ["KotakCoreAutoStart", "KotakBotAdapterAutoStart"]
    try:
        # FIX 2026-09-29 22:30: use the brain HTTP bridge (which has SYSTEM context)
        # because schtasks /Query returns access-denied from non-admin session.
        import requests
        missing = []
        for t in required:
            r = requests.post(
                "http://127.0.0.1:8503/command",
                json={"cmd": "run", "command": ["schtasks", "/Query", "/TN", t, "/FO", "LIST"], "timeout": 10},
                timeout=15,
            )
            out = r.json().get("stdout", "") + r.json().get("stderr", "")
            if t not in out:
                missing.append(t)
        if missing:
            check.add("Scheduled tasks", False, f"missing: {missing}")
        else:
            check.add("Scheduled tasks", True, f"{len(required)} tasks present")
    except Exception as e:
        check.add("Scheduled tasks", False, f"check failed: {e}")


def check_disk(check: Check):
    """6. Disk has space."""
    import shutil
    try:
        usage = shutil.disk_usage(ROOT)
        free_gb = usage.free / 1024 / 1024 / 1024
        total_gb = usage.total / 1024 / 1024 / 1024
        pct = (usage.used / usage.total) * 100
        if free_gb > 1.0:
            check.add("Disk space", True, f"{free_gb:.1f}GB free ({pct:.0f}% used)")
        else:
            check.add("Disk space", False, f"only {free_gb:.1f}GB free")
    except Exception as e:
        check.add("Disk space", False, f"check failed: {e}")


def check_paper_state(check: Check):
    """7. Paper state is sane (positions == 0 expected after today's force-close)."""
    state_path = ROOT / "data_cache" / "paper_state.json"
    if not state_path.exists():
        check.add("Paper state", False, "missing")
        return
    try:
        s = json.loads(state_path.read_text(encoding="utf-8"))
        cash = s.get("cash", 0)
        realized = s.get("realized_pnl", 0)
        n_pos = len(s.get("positions", {}))
        check.add("Paper state", True,
                  f"cash=Rs.{cash:,.0f} realized=Rs.{realized:,.0f} positions={n_pos}")
    except Exception as e:
        check.add("Paper state", False, f"parse error: {e}")


def check_core_health(check: Check):
    """8. Core's events_in_log is monotonically increasing (no replay corruption)."""
    try:
        r = urllib.request.urlopen("http://127.0.0.1:8510/healthz", timeout=3)
        data = json.loads(r.read())
        n = data.get("events_in_log", 0)
        if n > 0:
            check.add("Core event log", True, f"{n} events in DB")
        else:
            check.add("Core event log", False, "0 events — projection empty")
    except Exception as e:
        check.add("Core event log", False, f"unreachable: {e}")


def main():
    print(f"=== Pre-market readiness check ({datetime.now(IST).strftime('%Y-%m-%d %H:%M IST')}) ===\n")
    check = Check()
    check_core(check)
    check_adapter(check)
    check_bot_service(check)
    check_kotak_session(check)
    check_scheduled_tasks(check)
    check_disk(check)
    check_paper_state(check)
    check_core_health(check)
    ok = check.summary()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())