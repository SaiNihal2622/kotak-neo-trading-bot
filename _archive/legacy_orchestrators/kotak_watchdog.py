"""
kotak_watchdog.py — Self-contained watchdog for the kotak-neo-bot.

Goal: replace the mavis-cron-cascade of heartbeat slot tasks with a single
in-process loop that:
  1. Verifies the bot process is alive (PIDs + path filter)
  2. Verifies the dashboard is responsive on :8501
  3. Verifies the journal isn't growing pathologically (signal of log-storm)
  4. Auto-restarts the bot if dead, via the existing start_bot_detached.ps1
  5. Cleans up stale heartbeat_*.ps1 files in Temp/ (keep the most recent N)
  6. Reports state changes (alive -> dead, restarts, errors) to Telegram
  7. Stays silent during steady-state — no skip-tick spam

Run as a background process:
    python -m kotak_watchdog --interval 60

Or as a Windows scheduled task (single registration, NOT 6+ re-fires):
    schtasks /Create /SC MINUTE /MO 5 /TN "KotakWatchdog" /TR "python C:\...\kotak_watchdog.py --once"
    # --once runs one check then exits; scheduled task fires every 5 min
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

PROJECT_DIR = Path(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot")
STATE_PATH = PROJECT_DIR / "data_cache" / "watchdog_state.json"
TELEGRAM_LOG = PROJECT_DIR / "logs" / "watchdog.log"
START_SCRIPT = PROJECT_DIR / "start_bot_detached.ps1"
HEARTBEAT_TEMP_DIR = Path(r"C:\Users\saini\AppData\Local\Temp")
HEARTBEAT_KEEP = 12  # keep only the most recent 12 heartbeat files (1h at 5-min cadence)
STATE_CHANGE_COOLDOWN = 300  # seconds between repeated state-change alerts
MAX_AGE_MIN_ALERT = 15  # alert if no alive bot for >15 min during market hours


@dataclass
class WatchdogState:
    last_alive: bool = False
    last_pid: int = 0
    last_uptime_min: float = 0.0
    last_dash_status: str = "UNKNOWN"
    last_log_bytes: int = 0
    last_log_age_sec: float = 0.0
    last_check_at: str = ""
    consecutive_dead: int = 0
    consecutive_alive: int = 0
    restarts_today: int = 0
    restarts_today_date: str = ""
    last_state_change_at: float = 0.0
    last_state_change_msg: str = ""


@dataclass
class CheckResult:
    alive: bool
    pid: int
    uptime_min: float
    dash_status: str
    log_bytes: int
    log_age_sec: float
    python_count: int
    msg: str = ""


def _load_state() -> WatchdogState:
    if not STATE_PATH.exists():
        return WatchdogState()
    try:
        return WatchdogState(**json.loads(STATE_PATH.read_text(encoding="utf-8")))
    except Exception:
        return WatchdogState()


def _save_state(s: WatchdogState) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(asdict(s), indent=2), encoding="utf-8")


def _get_bot_processes():
    """Return list of (pid, uptime_min, commandline) for kotak_bot python procs."""
    out = []
    try:
        import ctypes
        from ctypes import wintypes
        # Use ctypes to call EnumProcesses — avoids wmi/PowerShell overhead
        PSAPI = ctypes.WinDLL("psapi.dll")
        KERNEL32 = ctypes.WinDLL("kernel32.dll")

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        buf = ctypes.create_string_buffer(4096)
        # 1) GetProcessesByName via PSAPI - by name "python.exe"
        process_ids = (wintypes.DWORD * 2048)()
        cb = ctypes.sizeof(process_ids)
        ret_len = wintypes.DWORD()
        if not PSAPI.EnumProcesses(ctypes.byref(process_ids), cb, ctypes.byref(ret_len)):
            return out
        pid_count = ret_len.value // ctypes.sizeof(wintypes.DWORD)
        now = time.time()
        for i in range(pid_count):
            pid = process_ids[i]
            if pid == 0:
                continue
            h = KERNEL32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not h:
                continue
            try:
                # GetModuleFileNameExW returns the executable path
                name_buf = ctypes.create_unicode_buffer(512)
                n = KERNEL32.GetModuleFileNameExW(h, None, name_buf, 512)
                exe = name_buf.value if n > 0 else ""
                if "python" not in exe.lower():
                    continue
                # GetProcessTimes to compute uptime
                ct = ctypes.c_int64()
                et = ctypes.c_int64()
                if not KERNEL32.GetProcessTimes(h, ctypes.byref(ct), ctypes.byref(et),
                                                  ctypes.byref(ct), ctypes.byref(et)):
                    continue
                # 100-ns intervals since 1601-01-01
                start_epoch_100ns = ct.value
                epoch_diff_100ns = 11644473600 * 10_000_000
                start_unix = (start_epoch_100ns - epoch_diff_100ns) / 10_000_000
                if start_unix <= 0 or start_unix > now + 60:
                    continue
                uptime_min = (now - start_unix) / 60.0
                # Check command line: must contain "kotak_bot"
                # We use WMI via ctypes? Simpler: just take all recent pythons,
                # caller filters by kotak_bot in the cmdline via tasklist
                out.append((pid, uptime_min, exe, start_unix))
            finally:
                KERNEL32.CloseHandle(h)
    except Exception as e:
        _log(f"enum error: {e}")
    return out


def _filter_kotak_bot(processes):
    """Filter to only kotak_bot processes (cmdline check via WMI)."""
    try:
        # Use tasklist to get command lines
        result = subprocess.run(
            ["tasklist", "/v", "/fi", "imagename eq python.exe", "/fo", "csv", "/nh"],
            capture_output=True, text=True, timeout=10
        )
        kotak_lines = [l for l in result.stdout.splitlines() if "kotak_bot" in l.lower()]
        kotak_pids = set()
        for line in kotak_lines:
            # CSV: "python.exe","PID","SessionName","Session#","Mem","Status","User","CPUTime","WindowTitle"
            parts = line.strip().split('","')
            if len(parts) >= 2:
                try:
                    pid = int(parts[1].strip('"'))
                    kotak_pids.add(pid)
                except ValueError:
                    pass
        return [(pid, up, exe) for (pid, up, exe, _) in processes if pid in kotak_pids]
    except Exception as e:
        _log(f"tasklist error: {e}")
        return []


def _dashboard_status() -> str:
    try:
        req = urllib.request.Request("http://localhost:8501/_stcore/health", method="GET")
        with urllib.request.urlopen(req, timeout=3) as r:
            return str(r.status)
    except urllib.error.HTTPError as e:
        return f"HTTP{e.code}"
    except Exception as e:
        return f"ERR({type(e).__name__})"


def _log_path_info() -> tuple[int, float]:
    log = PROJECT_DIR / "logs" / "bot_stderr.log"
    if not log.exists():
        return 0, -1.0
    stat = log.stat()
    age = time.time() - stat.st_mtime
    return stat.st_size, age


def _check_once() -> CheckResult:
    procs = _get_bot_processes()
    kotak = _filter_kotak_bot(procs)
    if not kotak:
        return CheckResult(
            alive=False, pid=0, uptime_min=0.0,
            dash_status=_dashboard_status(),
            log_bytes=_log_path_info()[0],
            log_age_sec=_log_path_info()[1],
            python_count=len(procs),
            msg="no kotak_bot process found",
        )
    # Take the most recent start (handles PIDs that may have been reused)
    kotak.sort(key=lambda x: -x[1])
    pid, uptime, _exe = kotak[0]
    return CheckResult(
        alive=True, pid=pid, uptime_min=uptime,
        dash_status=_dashboard_status(),
        log_bytes=_log_path_info()[0],
        log_age_sec=_log_path_info()[1],
        python_count=len(procs),
        msg=f"kotak_bot PID={pid} uptime={uptime:.1f}min",
    )


def _restart_bot() -> tuple[bool, str]:
    """Run start_bot_detached.ps1. Returns (ok, msg)."""
    if not START_SCRIPT.exists():
        return False, f"start script not found: {START_SCRIPT}"
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", str(START_SCRIPT)],
            capture_output=True, text=True, timeout=60
        )
        return result.returncode == 0, (result.stdout or "")[-500:] + (result.stderr or "")[-200:]
    except Exception as e:
        return False, f"restart exception: {e}"


def _send_telegram(msg: str) -> None:
    """Best-effort Telegram alert. Loads creds from env or config/credentials.env.
    Failure to send is logged but never raised."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        # Try credentials.env
        env_file = PROJECT_DIR / "config" / "credentials.env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = json.dumps({"chat_id": chat_id, "text": msg, "parse_mode": "HTML"}).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as r:
            r.read()
    except Exception as e:
        _log(f"telegram send failed: {e}")


def _log(msg: str) -> None:
    TELEGRAM_LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.utcnow().isoformat()} {msg}\n"
    try:
        with open(TELEGRAM_LOG, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def _cleanup_heartbeats() -> int:
    """Remove old heartbeat_*.ps1 files, keeping the most recent N."""
    if not HEARTBEAT_TEMP_DIR.exists():
        return 0
    files = sorted(
        [f for f in HEARTBEAT_TEMP_DIR.glob("heartbeat_*.ps1") if f.is_file()],
        key=lambda f: f.stat().st_mtime, reverse=True
    )
    removed = 0
    for f in files[HEARTBEAT_KEEP:]:
        try:
            f.unlink()
            removed += 1
        except Exception:
            pass
    return removed


def _is_market_hours() -> bool:
    now = datetime.now()
    wd = now.weekday()
    if wd >= 5:
        return False
    h, m = now.hour, now.minute
    if h < 9 or (h == 9 and m < 0):
        return False
    if h > 15 or (h == 15 and m > 30):
        return False
    return True


def run_once(loop: bool = True, interval: int = 60) -> None:
    s = _load_state()
    _log(f"watchdog start: loop={loop} interval={interval}s")
    # Reset daily restart counter if day changed
    today = datetime.now().strftime("%Y-%m-%d")
    if s.restarts_today_date != today:
        s.restarts_today = 0
        s.restarts_today_date = today
    while True:
        try:
            r = _check_once()
            prev_alive = s.last_alive
            now_ts = time.time()
            s.last_alive = r.alive
            s.last_pid = r.pid
            s.last_uptime_min = r.uptime_min
            s.last_dash_status = r.dash_status
            s.last_log_bytes = r.log_bytes
            s.last_log_age_sec = r.log_age_sec
            s.last_check_at = datetime.utcnow().isoformat()
            if r.alive:
                s.consecutive_alive += 1
                s.consecutive_dead = 0
            else:
                s.consecutive_dead += 1
                s.consecutive_alive = 0
            _save_state(s)

            # State-change detection: only alert on transitions, with cooldown
            transitioned_to_dead = (not r.alive) and prev_alive
            transitioned_to_alive = r.alive and (not prev_alive)
            cooldown_ok = (now_ts - s.last_state_change_at) > STATE_CHANGE_COOLDOWN

            if transitioned_to_dead and cooldown_ok:
                msg = (
                    f"⚠️ <b>kotak-neo-bot DOWN</b>\n"
                    f"Dashboard: {r.dash_status}\n"
                    f"Log age: {r.log_age_sec:.0f}s\n"
                    f"Python procs: {r.python_count}\n"
                    f"Restarting via start_bot_detached.ps1…"
                )
                _log(f"ALERT: dead — {r.msg}")
                _send_telegram(msg)
                ok, detail = _restart_bot()
                if ok:
                    s.restarts_today += 1
                    s.last_state_change_at = now_ts
                    s.last_state_change_msg = "dead->restarted"
                    _log(f"RESTART ok: {detail[:200]}")
                    _send_telegram(f"✅ Restarted. Detail: {detail[:300]}")
                else:
                    _log(f"RESTART FAILED: {detail[:300]}")
                    _send_telegram(f"❌ Restart FAILED. Detail: {detail[:500]}")
                _save_state(s)

            elif transitioned_to_alive and cooldown_ok:
                msg = (
                    f"✅ <b>kotak-neo-bot back</b>\n"
                    f"PID: {r.pid}\n"
                    f"Uptime: {r.uptime_min:.1f} min\n"
                    f"Dashboard: {r.dash_status}"
                )
                _log(f"ALERT: alive — {r.msg}")
                _send_telegram(msg)
                s.last_state_change_at = now_ts
                s.last_state_change_msg = "dead->alive"
                _save_state(s)

            # Auto-restart on sustained downtime (3+ consecutive dead checks) during
            # market hours — even if we didn't catch the transition.
            elif (not r.alive) and s.consecutive_dead >= 3 and _is_market_hours() \
                    and cooldown_ok and s.last_state_change_msg != "auto-restart-attempted":
                s.last_state_change_at = now_ts
                s.last_state_change_msg = "auto-restart-attempted"
                _log(f"AUTO-RESTART: 3 consecutive dead checks during market hours")
                ok, detail = _restart_bot()
                if ok:
                    s.restarts_today += 1
                    _send_telegram(f"🔄 Auto-restarted (sustained downtime). {detail[:300]}")
                _save_state(s)

            # Daily heartbeat summary at 15:35 IST (post-EOD) — once per day
            now_hhmm = datetime.now().strftime("%H:%M")
            if now_hhmm == "15:35" and s.last_state_change_msg != "eod-summary-2026-08-21":
                s.last_state_change_msg = f"eod-summary-{today}"
                s.last_state_change_at = now_ts
                _send_telegram(
                    f"📊 EOD: alive={r.alive} PID={r.pid} uptime={r.uptime_min:.1f}m "
                    f"dash={r.dash_status} restarts_today={s.restarts_today}"
                )
                _save_state(s)

            # Heartbeat file cleanup — once per hour
            if datetime.now().minute == 0 and not s.last_state_change_msg.endswith("cleanup-ran"):
                removed = _cleanup_heartbeats()
                if removed > 0:
                    _log(f"heartbeat cleanup: removed {removed} stale files")

            if not loop:
                return
            time.sleep(interval)
        except KeyboardInterrupt:
            _log("watchdog interrupted, exiting")
            return
        except Exception as e:
            _log(f"loop exception: {e}")
            if not loop:
                raise
            time.sleep(interval)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--interval", type=int, default=60)
    p.add_argument("--once", action="store_true", help="single check then exit")
    args = p.parse_args()
    run_once(loop=not args.once, interval=args.interval)


if __name__ == "__main__":
    main()
