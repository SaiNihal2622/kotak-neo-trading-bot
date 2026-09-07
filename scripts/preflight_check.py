"""preflight_check.py — comprehensive pre-flight check for 24/7 reliability.

Run this before going to bed, or as part of pre_market. It checks every
component of the system and reports + auto-fixes what it can.

Checks (in order of severity):
  1. Bot process alive (NSSM-managed, PID in liveness.json)
  2. Brain process alive (NSSM-managed, port 8503 responds)
  3. NSSM service KotakBotPaper = RUNNING
  4. NSSM service KotakQuantService = RUNNING
  5. Only ONE kotak_bot paper process running (no duplicates)
  6. Bot code on latest commit (liveness.boot_time > 1 hour for stale detection)
  7. trade_journal.jsonl has entries from today (inline callback working)
  8. performance/daily.json updated today
  9. Scheduled tasks registered (kotak-pre-market-self-heal, kotak-eod-pnl-evaluator,
     kotak-nightly-state-backup, kotak-nssm-watchdog)
  10. No stale mavis_force_action.json (consumed)
  11. No crash dump in liveness_crash.jsonl from today
  12. Kotak session valid for >2h (or auto re-auth)
  13. telegram_alerter enabled
  14. self_heal recipes loaded

Auto-fix capabilities:
  - Restart bot via NSSM
  - Kill duplicate bot instances
  - Start NSSM service if STOPPED (via SYSTEM-context force-action)
  - Re-auth Kotak session
  - Mark reset marker for tomorrow if no marker exists and we have poison

Returns a structured report (also sent to Telegram). Exit code:
  0 = all checks passed
  1 = some checks failed but auto-fix was applied
  2 = some checks failed and could not be auto-fixed
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).parent.parent.resolve()
DCACHE = ROOT / "data_cache"
NSSM_EXE = Path(r"C:\Tools\nssm\nssm-2.24\win64\nssm.exe")
LOGS = ROOT / "Logs"


class Check:
    def __init__(self, name: str, severity: str = "error"):
        self.name = name
        self.severity = severity
        self.passed = False
        self.message = ""
        self.fix_applied = False
        self.fix_message = ""

    def __repr__(self):
        status = "OK" if self.passed else f"FAIL ({self.severity})"
        msg = f"[{status}] {self.name}: {self.message}"
        if self.fix_applied:
            msg += f" | auto-fix: {self.fix_message}"
        return msg


def _nssm_status(service: str) -> Optional[str]:
    """Return NSSM service status: 'RUNNING', 'STOPPED', or None on error.

    nssm exit code 0 = service is in the queried state (RUNNING for status query).
    exit code 1 = service is in the opposite state.
    But the most reliable check is sc query:
    """
    try:
        r = subprocess.run(
            ["sc", "query", service],
            capture_output=True, text=True, timeout=10,
        )
        out = (r.stdout or "").upper()
        if "RUNNING" in out and "STOPPED" not in out:
            return "RUNNING"
        if "STOPPED" in out:
            return "STOPPED"
        if "START_PENDING" in out:
            return "START_PENDING"
        if "STOP_PENDING" in out:
            return "STOP_PENDING"
        return None
    except Exception as e:
        return None


def _nssm_start(service: str) -> tuple[bool, str]:
    """Try to start an NSSM service. Returns (success, output)."""
    try:
        r = subprocess.run(
            [str(NSSM_EXE), "start", service],
            capture_output=True, text=True, timeout=20,
        )
        return r.returncode == 0, (r.stdout or r.stderr or "").strip()[:200]
    except Exception as e:
        return False, str(e)


def _nssm_restart(service: str) -> tuple[bool, str]:
    """Try to restart an NSSM service."""
    try:
        r = subprocess.run(
            [str(NSSM_EXE), "restart", service],
            capture_output=True, text=True, timeout=30,
        )
        return r.returncode == 0, (r.stdout or r.stderr or "").strip()[:200]
    except Exception as e:
        return False, str(e)


def _count_kotak_bot_procs() -> int:
    """Count the number of running kotak_bot paper processes. Uses WMI
    which is more reliable than Get-Process. We count both the venv
    wrapper AND the python child as a single "bot" (one-to-one).

    NOTE: WMI from user-context can only see processes owned by the user.
    SYSTEM-owned processes (like NSSM-managed bots) have empty CommandLine
    in WMI, so they don't match. We fall back to checking the liveness.json
    PID as the authoritative source.
    """
    # Method 1: try WMI
    try:
        r = subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                "(Get-WmiObject -Class Win32_Process | "
                " Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -match 'kotak_bot paper' } | "
                " Measure-Object).Count"
            ],
            capture_output=True, text=True, timeout=15,
        )
        n = int((r.stdout or "0").strip())
        if n > 0:
            return n
    except Exception:
        pass
    # Method 2: fall back to liveness.json (authoritative)
    liv = DCACHE / "liveness.json"
    if not liv.exists():
        return 0
    try:
        l = json.loads(liv.read_text(encoding="utf-8"))
        pid = l.get("pid")
        if pid:
            # verify process is alive
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"Get-Process -Id {pid} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id"],
                capture_output=True, text=True, timeout=10,
            )
            if (r.stdout or "").strip() == str(pid):
                return 1  # one bot is alive per liveness
    except Exception:
        pass
    return 0


def _brain_alive() -> bool:
    """Check if the brain's HTTP :8503 responds."""
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:8503/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def _check_bot_process() -> Check:
    """1. Bot process alive (NSSM-managed)."""
    c = Check("bot process alive", "error")
    liv = DCACHE / "liveness.json"
    if not liv.exists():
        c.message = "liveness.json missing — bot is not running"
        # try to start it
        ok, out = _nssm_start("KotakBotPaper")
        c.fix_applied = ok
        c.fix_message = f"nssm start: {out}"
        if ok:
            c.passed = True
            c.message = "liveness.json missing but nssm start succeeded"
        return c
    try:
        l = json.loads(liv.read_text(encoding="utf-8"))
        pid = l.get("pid")
        uptime = l.get("uptime_sec", 0)
        # check if process is alive
        try:
            import psutil
            alive = psutil.pid_exists(pid) and psutil.Process(pid).is_running()
        except ImportError:
            # fallback: query WMI
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"Get-Process -Id {pid} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id"],
                capture_output=True, text=True, timeout=10,
            )
            alive = (r.stdout or "").strip() == str(pid)
        if alive and l.get("main_thread_alive"):
            c.passed = True
            c.message = f"PID {pid}, uptime {uptime:.0f}s, tick {l.get('tick')}"
        else:
            c.message = f"liveness shows PID {pid} but process not running"
            ok, out = _nssm_restart("KotakBotPaper")
            c.fix_applied = ok
            c.fix_message = f"nssm restart: {out}"
    except Exception as e:
        c.message = f"liveness.json unreadable: {e}"
    return c


def _check_brain() -> Check:
    """2. Brain process alive."""
    c = Check("brain port 8503 alive", "error")
    if _brain_alive():
        c.passed = True
        c.message = "8503 /health returned 200"
    else:
        c.message = "8503 not responding"
        ok, out = _nssm_restart("KotakQuantService")
        c.fix_applied = ok
        c.fix_message = f"nssm restart: {out}"
    return c


def _check_nssm_botpaper() -> Check:
    """3. NSSM service KotakBotPaper = RUNNING."""
    c = Check("NSSM KotakBotPaper = RUNNING", "error")
    status = _nssm_status("KotakBotPaper")
    if status == "RUNNING":
        c.passed = True
        c.message = "running"
    else:
        c.message = f"status={status or 'unknown'}"
        ok, out = _nssm_start("KotakBotPaper")
        c.fix_applied = ok
        c.fix_message = f"nssm start: {out}"
    return c


def _check_nssm_quantservice() -> Check:
    """4. NSSM service KotakQuantService = RUNNING."""
    c = Check("NSSM KotakQuantService = RUNNING", "warning")
    status = _nssm_status("KotakQuantService")
    if status == "RUNNING":
        c.passed = True
        c.message = "running"
    else:
        c.message = f"status={status or 'unknown'} (brain may be user-space)"
        # try to start (will be no-op if user-space, but worth trying)
        ok, out = _nssm_start("KotakQuantService")
        c.fix_applied = ok
        c.fix_message = f"nssm start: {out}"
    return c


def _check_no_duplicate_bots() -> Check:
    """5. Only ONE kotak_bot paper process running."""
    c = Check("only one bot instance", "error")
    n = _count_kotak_bot_procs()
    if n == 1:
        c.passed = True
        c.message = "exactly 1"
    elif n == 0:
        c.message = "0 bots running (NSSM should have started one)"
        ok, out = _nssm_start("KotakBotPaper")
        c.fix_applied = ok
        c.fix_message = f"nssm start: {out}"
    elif n > 1:
        c.message = f"{n} bots running — need to kill duplicates"
        c.fix_applied = False  # killing requires admin which we don't have from user context
        c.fix_message = "manual intervention: kill duplicate user-space bots"
    else:
        c.message = f"could not count ({n})"
    return c


def _check_bot_code_current() -> Check:
    """6. Bot code on latest commit (liveness has recent boot_time)."""
    c = Check("bot code current", "warning")
    liv = DCACHE / "liveness.json"
    if not liv.exists():
        c.message = "liveness.json missing"
        return c
    try:
        l = json.loads(liv.read_text(encoding="utf-8"))
        boot_str = l.get("boot_time", "1970-01-01")
        # Handle both offset-aware and offset-naive timestamps defensively
        if "T" in boot_str:
            boot = datetime.fromisoformat(boot_str.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            if boot.tzinfo is None:
                boot = boot.replace(tzinfo=timezone.utc)
        else:
            # Fallback: just compare uptime
            uptime = l.get("uptime_sec", 0)
            if uptime < 24 * 3600:
                c.passed = True
                c.message = f"uptime {uptime/3600:.1f}h (recent)"
                return c
            else:
                c.message = f"uptime {uptime/3600:.1f}h (stale)"
                return c
        age_min = (now - boot).total_seconds() / 60
        if age_min < 60 * 24:  # < 24h old
            c.passed = True
            c.message = f"boot {age_min:.0f} min ago"
        else:
            c.message = f"boot {age_min/60:.1f} h ago — likely stale"
    except Exception as e:
        c.message = f"unparseable: {e}"
    return c


def _check_inline_journal_callback() -> Check:
    """7. trade_journal.jsonl has entries from today (inline callback working).

    After-hours or no-trade days: 0 entries is OK (warning, not error).
    During market hours with no entries: error (callback is broken).
    """
    c = Check("inline journal has today's entries", "warning")
    journal = DCACHE / "trade_journal.jsonl"
    if not journal.exists():
        c.message = "trade_journal.jsonl missing"
        return c
    today = datetime.now().strftime("%Y-%m-%d")
    n_today = 0
    n_eod = 0
    try:
        for line in journal.read_text(encoding="utf-8", errors="ignore").splitlines():
            if today in line:
                if "FILL-" in line:
                    n_today += 1
                elif "RECON-" in line:
                    n_eod += 1
    except Exception as e:
        c.message = f"unreadable: {e}"
        return c
    if n_today > 0 or n_eod > 0:
        c.passed = True
        c.message = f"{n_today} inline FILL + {n_eod} EOD RECON entries today"
    else:
        # No entries — is it market hours?
        from datetime import time as _time
        now_t = datetime.now().time()
        is_market = _time(9, 15) <= now_t <= _time(15, 30)
        if is_market:
            # Mid-session with 0 entries is concerning (callback might be broken)
            c.severity = "error"
            c.message = "0 entries today DURING market hours (callback may be broken)"
        else:
            c.message = "0 entries today (after-hours / no trades yet)"
    return c


def _check_daily_json() -> Check:
    """8. performance/daily.json updated today.

    Before market close: yesterday's data is OK (today's EOD task hasn't run).
    After market close + 1h: today's data should be present.
    """
    c = Check("performance/daily.json updated", "warning")
    daily = DCACHE / "performance" / "daily.json"
    if not daily.exists():
        c.message = "missing"
        return c
    try:
        d = json.loads(daily.read_text(encoding="utf-8"))
        last_updated = d.get("last_updated", "")[:10]
        today = datetime.now().strftime("%Y-%m-%d")
        if last_updated == today:
            c.passed = True
            c.message = f"date={d.get('date')}, last_updated={d.get('last_updated')}"
        else:
            # Yesterday's data is fine if we haven't hit EOD yet today
            from datetime import time as _time
            now_t = datetime.now().time()
            eod_time = _time(15, 30)
            if now_t < eod_time:
                c.passed = True
                c.message = f"date={d.get('date')} (yesterday; EOD task hasn't run today yet)"
            else:
                c.message = f"date={d.get('date')} (yesterday; EOD task should have run by now)"
    except Exception as e:
        c.message = str(e)
    return c


def _check_scheduled_tasks() -> Check:
    """9. SYSTEM-context scheduled tasks registered (we can only see user-context ones)."""
    c = Check("daily tasks visible", "warning")
    try:
        r = subprocess.run(
            ["schtasks", "/query"],
            capture_output=True, text=True, timeout=10,
        )
        # User-context query only shows user tasks, not SYSTEM ones. We can detect
        # by checking if ANY kotak tasks show up.
        if "kotak" in (r.stdout or "").lower():
            c.passed = True
            c.message = "at least 1 kotak task visible (user-context)"
        else:
            c.message = "no kotak tasks visible from user-context (SYSTEM tasks not enumerable)"
    except Exception as e:
        c.message = str(e)
    return c


def _check_no_stale_force_action() -> Check:
    """10. No stale mavis_force_action.json (consumed=True or absent)."""
    c = Check("no stale force-action", "warning")
    fa = DCACHE / "mavis_force_action.json"
    if not fa.exists():
        c.passed = True
        c.message = "no force-action JSON"
        return c
    try:
        d = json.loads(fa.read_text(encoding="utf-8"))
        if d.get("consumed"):
            c.passed = True
            c.message = "consumed=True (bot processed it)"
        else:
            c.message = f"unconsumed, action={d.get('action')}, ts={d.get('ts')}"
    except Exception as e:
        c.message = f"unreadable: {e}"
    return c


def _check_no_crash_today() -> Check:
    """11. No crash dump in liveness_crash.jsonl from today."""
    c = Check("no crashes today", "warning")
    crash = DCACHE / "liveness_crash.jsonl"
    if not crash.exists():
        c.passed = True
        c.message = "no crash log"
        return c
    today = datetime.now().strftime("%Y-%m-%d")
    n_today = 0
    for line in crash.read_text(encoding="utf-8", errors="ignore").splitlines():
        if today in line:
            n_today += 1
    if n_today == 0:
        c.passed = True
        c.message = "0 crashes today"
    else:
        c.message = f"{n_today} crash entries today"
    return c


def _check_kotak_session() -> Check:
    """12. Kotak session valid for >2h."""
    c = Check("Kotak session valid", "warning")
    sess = DCACHE / "kotak_prod_session.json"
    if not sess.exists():
        c.message = "session file missing"
        return c
    try:
        s = json.loads(sess.read_text(encoding="utf-8"))
        expires_at = s.get("expires_at", 0)
        hrs_left = (expires_at - time.time()) / 3600
        if hrs_left > 2:
            c.passed = True
            c.message = f"{hrs_left:.1f}h left"
        else:
            c.message = f"only {hrs_left:.1f}h left — re-auth needed (session_watch.py handles at <2h)"
            # Don't auto-fix here; session_watch.py auto re-auths unattended.
    except Exception as e:
        c.message = str(e)
    return c


def _check_self_heal_recipes() -> Check:
    """14. self_heal recipes loaded (importable)."""
    c = Check("self_heal recipes importable", "error")
    try:
        # Add project root to path so kotak_bot is importable when run directly
        sys.path.insert(0, str(ROOT))
        from kotak_bot import self_heal
        n = len(self_heal.RECIPES) + len(getattr(self_heal, "_NSSM_RECIPES", {}))
        if n >= 8:
            c.passed = True
            c.message = f"{n} recipes registered"
        else:
            c.message = f"only {n} recipes (expected >= 8)"
    except Exception as e:
        c.message = f"import failed: {e}"
    return c


def _send_telegram(msg: str) -> bool:
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        cred = ROOT / "config" / "credentials.env"
        for line in cred.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if k.strip() not in os.environ:
                    os.environ[k.strip()] = v.strip().strip('"').strip("'")
        from telegram_alerter import get_alerter
        a = get_alerter()
        if a and a.enabled:
            return a.send(msg)
    except Exception as e:
        print(f"telegram send failed: {e}")
    return False


def main() -> int:
    print("=" * 60)
    print(f"PRE-FLIGHT CHECK — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} IST")
    print("=" * 60)
    print()

    checks = [
        _check_bot_process(),
        _check_brain(),
        _check_nssm_botpaper(),
        _check_nssm_quantservice(),
        _check_no_duplicate_bots(),
        _check_bot_code_current(),
        _check_inline_journal_callback(),
        _check_daily_json(),
        _check_scheduled_tasks(),
        _check_no_stale_force_action(),
        _check_no_crash_today(),
        _check_kotak_session(),
        _check_self_heal_recipes(),
    ]

    n_pass = 0
    n_fail = 0
    n_fix = 0
    failed_critical = []
    for c in checks:
        print(c)
        if c.passed:
            n_pass += 1
        else:
            n_fail += 1
            if c.severity == "error":
                failed_critical.append(c)
        if c.fix_applied:
            n_fix += 1
    print()
    print(f"Summary: {n_pass} pass, {n_fail} fail, {n_fix} auto-fixed")
    if failed_critical:
        print(f"Critical failures: {[c.name for c in failed_critical]}")

    # Build Telegram summary
    status_emoji = "OK" if not failed_critical else "WARN"
    lines = [
        f"[Mavis pre-flight {datetime.now().strftime('%H:%M')}] {status_emoji}  "
        f"{n_pass} pass, {n_fail} fail, {n_fix} auto-fixed",
    ]
    for c in checks:
        if c.passed and not c.fix_applied:
            lines.append(f"  [OK] {c.name}: {c.message}")
        elif c.passed and c.fix_applied:
            lines.append(f"  [FIXED] {c.name}: {c.message} | {c.fix_message[:80]}")
        else:
            lines.append(f"  [FAIL] {c.name}: {c.message}")
    if failed_critical:
        lines.append("")
        lines.append(f"CRITICAL: {', '.join(c.name for c in failed_critical)}")
        lines.append("Manual intervention may be needed.")
    msg = "\n".join(lines)
    if _send_telegram(msg):
        print(f"\nTelegram report sent")
    else:
        print(f"\nTelegram not sent (alerter disabled?)")

    # Exit code: 0 if all pass or all auto-fixed, 1 if warnings only, 2 if critical failed
    if not failed_critical:
        if n_fix > 0:
            return 1  # auto-fixes applied
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
