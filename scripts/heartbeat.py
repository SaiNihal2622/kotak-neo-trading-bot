"""Kotak Heartbeat - deterministic 5-min health check + restart.

Runs every 5 min via the `heartbeat-next-tick` cron (cronId
d9fdcd69-b4e0-4f88-8368-7b4ab52f841c). Replaces the previous LLM-driven
heartbeat prompt that was silently breaking on
`context_compaction_failed: Context is too large for checkpoint
generation` (turns 306+ had grown past the per-turn checkpoint budget).
The LLM is now a thin shell that just calls this script and reports.

Responsibilities (in order):
  1. Check bot is alive (psutil, 4h window filter, then unfiltered
     second check to avoid the 2h false-zero that happens around 10:30).
  2. Check dashboard HTTP 200 on :8501 /_stcore/health.
  3. Check the ACTIVE bot log is fresh (Logs\bot_stderr.log — the
     NSSM-managed one, NOT the cwd-relative root file that is frozen
     at 2026-08-20 02:27).
  4. Restart the bot (market hours only, 9:00-15:30 IST Mon-Fri) and
     the dashboard (any time).
  5. Send a Telegram alert on actual restart, NOT on routine ticks.

Writes one JSONL record per tick to data_cache/heartbeat_history.jsonl
(rotated at HISTORY_KEEP=720 = 60h of 5-min ticks). Prints a one-line
status to stdout for the cron log.

Path: C:\\Users\\saini\\.minimax-agent\\projects\\kotak-neo-bot\\scripts\\heartbeat.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DATA_CACHE = ROOT / "data_cache"
LOGS = ROOT / "Logs"
LOG_PATH = LOGS / "bot_stderr.log"            # NSSM-managed, ACTIVE
STATE_FILE = DATA_CACHE / "heartbeat_latest.json"
HISTORY_FILE = DATA_CACHE / "heartbeat_history.jsonl"
CREDS_PATH = ROOT / "config" / "credentials.env"
PY_EXE = ROOT / ".venv" / "Scripts" / "python.exe"

BOT_PATH_FILTER = "kotak-neo-bot"
BOT_4H_WINDOW = timedelta(hours=4)
DASHBOARD_URL = "http://127.0.0.1:8501/_stcore/health"
DASHBOARD_TIMEOUT_SEC = 3
LOG_MAX_AGE_SEC = 600              # log must be touched in last 10 min
TELEGRAM_COOLDOWN_SEC = 1800       # 30 min between restart alerts
HISTORY_KEEP = 720                 # 60h of 5-min ticks

# IST = UTC+5:30
IST = timezone(timedelta(hours=5, minutes=30))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_ist() -> datetime:
    return datetime.now(IST)


def _now_ist_iso() -> str:
    return _now_ist().isoformat()


def _read_creds() -> tuple[str | None, str | None]:
    if not CREDS_PATH.exists():
        return None, None
    token = chat_id = None
    for raw in CREDS_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("TELEGRAM_BOT_TOKEN="):
            token = line.split("=", 1)[1].strip().strip('"').strip("'")
        elif line.startswith("TELEGRAM_CHAT_ID="):
            chat_id = line.split("=", 1)[1].strip().strip('"').strip("'")
    return token, chat_id


def _is_market_hours(now: datetime) -> bool:
    if now.weekday() >= 5:                           # Sat/Sun
        return False
    minutes = now.hour * 60 + now.minute
    return 9 * 60 <= minutes <= 15 * 60 + 30         # 09:00-15:30 inclusive


def _count_bot_procs(window: timedelta | None) -> int:
    """Count python processes whose path contains the project filter.

    If `window` is provided, only processes started within that window
    are counted (avoids 2h false-zero after 10:30 once NSSM has the
    long-lived bot parented to yesterday's launch).
    """
    cutoff = (_now_ist() - window) if window else None
    n = 0
    for proc in psutil.process_iter(["pid", "name", "create_time"]):
        try:
            if proc.info["name"] != "python.exe":
                continue
            cmdline = " ".join(proc.cmdline() or [])
            if BOT_PATH_FILTER not in cmdline:
                continue
            if cutoff is not None:
                # psutil's create_time is a unix epoch; convert to IST for compare
                created = datetime.fromtimestamp(proc.info["create_time"], tz=IST)
                if created < cutoff:
                    continue
            n += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return n


def _check_dashboard() -> tuple[int | None, str]:
    """Return (status_code, error). status_code None on connection error."""
    import httpx
    try:
        r = httpx.get(DASHBOARD_URL, timeout=DASHBOARD_TIMEOUT_SEC)
        return r.status_code, ""
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def _check_log() -> dict:
    if not LOG_PATH.exists():
        return {"available": False, "reason": "missing"}
    age = time.time() - LOG_PATH.stat().st_mtime
    return {
        "available": True,
        "path": str(LOG_PATH),
        "age_sec": round(age, 1),
        "fresh": age < LOG_MAX_AGE_SEC,
        "size_bytes": LOG_PATH.stat().st_size,
    }


def _restart_bot() -> int | None:
    """Start a fresh paper bot. Returns the new PID or None on failure.

    Only valid during market hours; caller gates that.
    """
    if not PY_EXE.exists():
        return None
    # Match NSSM's launch pattern: stdout/stderr to root-relative log files
    # (NSSM does this; we follow suit so the bot_stderr.log the watchdog
    # reads stays current).
    log_dir = ROOT
    try:
        proc = subprocess.Popen(
            [str(PY_EXE), "-u", "-m", "kotak_bot", "paper"],
            cwd=str(ROOT),
            stdout=open(log_dir / "bot_stdout.log", "ab"),
            stderr=open(log_dir / "bot_stderr.log", "ab"),
            creationflags=0x00000008,  # DETACHED_PROCESS on Windows
        )
        return proc.pid
    except Exception as e:
        print(f"[heartbeat] bot restart failed: {e}", file=sys.stderr)
        return None


def _restart_dashboard() -> int | None:
    if not PY_EXE.exists():
        return None
    try:
        proc = subprocess.Popen(
            [str(PY_EXE), "-u", "-m", "streamlit", "run",
             "dashboard/app.py",
             "--server.port=8501", "--server.headless=true"],
            cwd=str(ROOT),
            creationflags=0x00000008,  # DETACHED_PROCESS
        )
        return proc.pid
    except Exception as e:
        print(f"[heartbeat] dashboard restart failed: {e}", file=sys.stderr)
        return None


def _send_telegram(text: str) -> bool:
    import httpx
    token, chat_id = _read_creds()
    if not token or not chat_id:
        return False
    try:
        r = httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
        return r.status_code == 200
    except Exception as e:
        print(f"[heartbeat] telegram send failed: {e}", file=sys.stderr)
        return False


def _maybe_alert_telegram(actions: list[str]) -> bool:
    """Send Telegram only if real actions were taken AND cooldown elapsed."""
    if not actions:
        return False
    last_alert = 0.0
    if STATE_FILE.exists():
        try:
            prev = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            last_alert = float(prev.get("last_telegram_at", 0.0))
        except Exception:
            pass
    if time.time() - last_alert < TELEGRAM_COOLDOWN_SEC:
        return False
    text = "[heartbeat] ACTIONS TAKEN\n\n" + "\n".join(f"- {a}" for a in actions)
    if _send_telegram(text):
        return True
    return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    DATA_CACHE.mkdir(parents=True, exist_ok=True)
    now = _now_ist()
    mkt = _is_market_hours(now)

    # 1. Bot alive check (4h window first, then unfiltered second check)
    alive4 = _count_bot_procs(BOT_4H_WINDOW)
    if alive4 == 0 and mkt:
        alive_any = _count_bot_procs(None)
    else:
        alive_any = alive4
    bot_alive = alive_any > 0

    # 2. Dashboard alive
    dash_code, dash_err = _check_dashboard()
    dash_alive = dash_code == 200

    # 3. Log fresh
    log = _check_log()

    actions: list[str] = []
    restart_pid: int | None = None

    # 4. Restart if dead (market hours for bot, anytime for dashboard)
    if not bot_alive and mkt:
        restart_pid = _restart_bot()
        if restart_pid:
            actions.append(f"bot was down, restarted. PID={restart_pid}")
        else:
            actions.append("bot was down, RESTART FAILED")

    if not dash_alive:
        dash_pid = _restart_dashboard()
        if dash_pid:
            actions.append(f"dashboard was down, restarted. PID={dash_pid}")
        else:
            actions.append("dashboard was down, RESTART FAILED")

    sent = _maybe_alert_telegram(actions)

    audit = {
        "ts": _now_ist_iso(),
        "epoch": int(time.time()),
        "mkt": mkt,
        "alive4": alive4,
        "alive_any": alive_any,
        "bot_alive": bot_alive,
        "dash": dash_code if dash_alive else f"ERR:{dash_err}",
        "log_bytes": log.get("size_bytes"),
        "log_age_sec": log.get("age_sec"),
        "log_fresh": log.get("fresh"),
        "actions": actions,
        "telegram_sent": sent,
    }
    if sent:
        audit["last_telegram_at"] = time.time()

    # Persist
    STATE_FILE.write_text(json.dumps(audit, indent=2, default=str), encoding="utf-8")
    try:
        with HISTORY_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(audit, default=str) + "\n")
    except Exception as e:
        print(f"[heartbeat] history append failed: {e}", file=sys.stderr)
    # Roll history
    try:
        if HISTORY_FILE.exists():
            lines = HISTORY_FILE.read_text(encoding="utf-8").splitlines()
            if len(lines) > HISTORY_KEEP:
                HISTORY_FILE.write_text("\n".join(lines[-HISTORY_KEEP:]) + "\n",
                                        encoding="utf-8")
    except Exception:
        pass

    # Compact stdout
    if actions:
        print(f"[heartbeat] ACTIONS: {'; '.join(actions)} | telegram={sent}")
    else:
        print(
            f"[heartbeat] OK | MKT={mkt} alive4={alive4}/any={alive_any} "
            f"dash={dash_code} log={log.get('size_bytes')}B "
            f"age={log.get('age_sec')}s"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
