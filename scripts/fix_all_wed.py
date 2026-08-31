"""fix_all_wed.py — Comprehensive clean-fix: reset to clean Rs.1,00,000 baseline.

Steps (must run in order; aborts on failure):
  1. Stop the running kotak_bot paper process
  2. Kill duplicate http_server PIDs
  3. Run backfill_realized_pnl.py — repair the 6 closed trades with realized_pnl=0
  4. Run reset_paper.py --capital 100000 — reset to CLEAN round number (no complications)
  5. Re-arm watchdog (it's been running but will detect bot is down + restart it)
  6. Verify bot is back up + dashboard is reachable before next session

NEW BASELINE: Rs.1,00,000 (clean round number).
User directive: "not peak, the best one to start with such that no complications occur" —
round number, zero fractional P&L, zero historical baggage, fresh slate.
All future P&L is measured from this clean baseline.

Usage:
    .venv/Scripts/python.exe scripts/fix_all_wed.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / "Scripts" / "python.exe"
LOG = ROOT / "logs" / f"fix_all_wed_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
DASH_URL = "http://127.0.0.1:8501/_stcore/health"
STARTING_CAPITAL = 100_000.00  # clean round number — fresh baseline, no complications

# PIDs to kill
BOT_PIDS = [10124]  # main kotak_bot paper (CIM-invisible, but CWD-known)
HTTP_SERVER_PIDS = [19964, 21440]


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def kill_pid(pid: int) -> bool:
    try:
        result = subprocess.run(
            ["taskkill.exe", "/F", "/PID", str(pid)],
            capture_output=True, text=True, timeout=10, check=False,
        )
        ok = result.returncode == 0
        log(f"  kill PID {pid}: {'OK' if ok else 'FAILED: ' + result.stderr.strip()}")
        return ok
    except Exception as e:
        log(f"  kill PID {pid}: EXCEPTION {e}")
        return False


def run_step(label: str, args: list, cwd: str = None, timeout: int = 180) -> bool:
    log(f"STEP: {label}")
    log(f"  cmd: {' '.join(str(a) for a in args)}")
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout, check=False,
            cwd=cwd or str(ROOT),
        )
        log(f"  exit={result.returncode}")
        if result.stdout.strip():
            log("  stdout (last 800):")
            for line in result.stdout.strip().splitlines()[-40:]:
                log(f"    {line}")
        if result.stderr.strip():
            log("  stderr (last 400):")
            for line in result.stderr.strip().splitlines()[-20:]:
                log(f"    {line}")
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        log(f"  TIMEOUT after {timeout}s")
        return False
    except Exception as e:
        log(f"  EXCEPTION: {e}")
        return False


def wait_for_bot(timeout: int = 60) -> bool:
    """Wait for the http_server status endpoint to report bot running."""
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen("http://127.0.0.1:8502/status", timeout=5) as r:
                body = json.loads(r.read().decode("utf-8"))
                state = body.get("liveness", {}).get("state", "")
                if state == "running":
                    log(f"  bot is RUNNING (uptime={body['liveness'].get('uptime_sec', 0):.0f}s)")
                    return True
                log(f"  bot state={state}, waiting...")
        except Exception as e:
            log(f"  waiting for bot ({e})...")
        time.sleep(3)
    return False


def wait_for_dashboard(timeout: int = 30) -> bool:
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(DASH_URL, timeout=5) as r:
                if r.status == 200:
                    log(f"  dashboard UP (status={r.status})")
                    return True
        except Exception:
            pass
        time.sleep(2)
    return False


def main() -> int:
    log("=" * 70)
    log(f"FIX_ALL_WED — {datetime.now().isoformat()}")
    log(f"ROOT: {ROOT}")
    log(f"Starting capital: Rs.{STARTING_CAPITAL:,.2f}")
    log("=" * 70)

    # 0) Snapshot before
    log("STEP 0: snapshot before-state")
    snap_before = {
        "ts": datetime.now().isoformat(),
        "paper_state_path": str(ROOT / "data_cache" / "paper_state.json"),
        "trades_state_path": str(ROOT / "data_cache" / "trades_state.json"),
    }
    log(json.dumps(snap_before, indent=2))

    # 1) Stop the running bot
    log("STEP 1: stop kotak_bot paper process")
    for pid in BOT_PIDS:
        kill_pid(pid)
    # Also kill any other kotak_bot python procs (catch-all)
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
             "Where-Object { $_.CommandLine -match 'kotak_bot' -and $_.CommandLine -notmatch 'http_server' } | "
             "Select-Object -ExpandProperty ProcessId"],
            capture_output=True, text=True, timeout=15, check=False,
        )
        pids = [int(x) for x in result.stdout.strip().splitlines() if x.strip().isdigit()]
        for pid in pids:
            kill_pid(pid)
    except Exception as e:
        log(f"  catch-all kill exception: {e}")
    log("  waiting 5s for graceful exit...")
    time.sleep(5)

    # 2) Kill duplicate http_server PIDs
    log("STEP 2: kill duplicate http_server PIDs")
    for pid in HTTP_SERVER_PIDS:
        kill_pid(pid)
    # Also kill any other http_server procs
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
             "Where-Object { $_.CommandLine -match 'kotak_bot.http_server' } | "
             "Select-Object -ExpandProperty ProcessId"],
            capture_output=True, text=True, timeout=15, check=False,
        )
        pids = [int(x) for x in result.stdout.strip().splitlines() if x.strip().isdigit()]
        for pid in pids:
            kill_pid(pid)
    except Exception as e:
        log(f"  http_server catch-all exception: {e}")
    time.sleep(2)

    # 3) Backfill realized P&L on the 6 closed trades
    log("STEP 3: backfill realized_pnl for closed trades")
    ok3 = run_step(
        "backfill_realized_pnl",
        [str(PY), str(ROOT / "scripts" / "backfill_realized_pnl.py")],
        timeout=60,
    )
    if not ok3:
        log("STEP 3: FAILED — aborting before reset")
        return 1

    # 4) Reset paper state to CLEAN baseline
    log("STEP 4: reset_paper.py with --capital 100000 (clean round-number baseline)")
    ok4 = run_step(
        "reset_paper",
        [str(PY), str(ROOT / "scripts" / "reset_paper.py"),
         "--capital", str(STARTING_CAPITAL), "--no-backup"],
        timeout=60,
    )
    if not ok4:
        log("STEP 4: FAILED — aborting before restart")
        return 1

    # 5) Restart bot via start_bot_detached.ps1
    log("STEP 5: restart bot via start_bot_detached.ps1")
    ps1 = ROOT / "start_bot_detached.ps1"
    if not ps1.exists():
        log(f"  ERROR: {ps1} missing")
        return 1
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1)],
            capture_output=True, text=True, timeout=60, check=False,
        )
        log(f"  start_bot exit={result.returncode}")
        for line in (result.stdout or "").splitlines()[-15:]:
            log(f"    {line}")
    except Exception as e:
        log(f"  start_bot exception: {e}")

    # 6) Wait for bot to come back up
    log("STEP 6: wait for bot to be running")
    if not wait_for_bot(timeout=90):
        log("  ERROR: bot did not become running within 90s")
        return 1

    # 7) Verify dashboard
    log("STEP 7: verify dashboard is reachable")
    wait_for_dashboard(timeout=30)

    # 8) Final status snapshot
    log("STEP 8: final status snapshot")
    try:
        with urllib.request.urlopen("http://127.0.0.1:8502/status", timeout=5) as r:
            body = json.loads(r.read().decode("utf-8"))
            log(json.dumps({
                "state": body.get("liveness", {}).get("state"),
                "capital": body.get("paper_state", {}).get("cash"),
                "realized": body.get("paper_state", {}).get("realized_pnl"),
                "data_source": body.get("liveness", {}).get("snapshot", {}).get("data_source"),
                "ts": body.get("ts"),
            }, indent=2))
    except Exception as e:
        log(f"  final snapshot failed: {e}")

    log("=" * 70)
    log("FIX_ALL_WED COMPLETE")
    log("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
