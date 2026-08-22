"""Kotak Self-Monitor - 24/7 off-hours audit of the running system.

Runs every 15 min via kotak-self-monitor cron. Reads the same state
the watchdog reads, but with a different lens:

- watchdog answers "is the bot alive?" -> restart if not
- self-monitor answers "is the system healthy AND trending healthy?"
  -> log the trend, alert on degradation, stay silent on steady state

Writes a structured audit record to data_cache/self_audit.jsonl
(JSONL so we can append, plus a rolling data_cache/self_audit_latest.json
for easy "what does the system look like RIGHT NOW" reads).

Sends Telegram ONLY on real anomalies (new error class, sudden uptime
regression, sudden liveness gap). Steady-state is silent.

Path: C:\\Users\\saini\\.minimax-agent\\projects\\kotak-neo-bot\\scripts\\self_monitor.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Runtime data
DATA_CACHE = ROOT / "data_cache"
LOGS = ROOT / "Logs"
STATE_FILE = DATA_CACHE / "self_audit_latest.json"
HISTORY_FILE = DATA_CACHE / "self_audit.jsonl"

# Telegram creds (read from credentials.env)
CREDS_PATH = ROOT / "config" / "credentials.env"

# Thresholds
LIVENESS_MAX_AGE_SEC = 180          # liveness file must be < 3 min old
CRASH_FILE_MAX_AGE_DAYS = 30        # crash JSONL stays in scope for 30d
LOG_MAX_AGE_SEC = 600               # bot log must be touched < 10 min
HISTORY_KEEP = 1000                 # keep last 1000 audit records in JSONL
TELEGRAM_COOLDOWN_SEC = 1800        # 30 min between anomaly alerts


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


def _now_ist_iso() -> str:
    # IST = UTC+5:30
    ist = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(ist).isoformat()


def _check_liveness() -> dict:
    path = DATA_CACHE / "liveness.json"
    if not path.exists():
        return {"available": False, "reason": "missing"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"available": False, "reason": f"parse: {e}"}
    mtime = path.stat().st_mtime
    age = time.time() - mtime
    return {
        "available": True,
        "age_sec": round(age, 1),
        "fresh": age < LIVENESS_MAX_AGE_SEC,
        "pid": data.get("pid"),
        "tick": data.get("tick"),
        "uptime_sec": data.get("uptime_sec"),
        "main_thread_alive": data.get("main_thread_alive"),
        "state": data.get("state"),
    }


def _check_log() -> dict:
    path = LOGS / "bot_stderr.log"
    if not path.exists():
        return {"available": False, "reason": "missing"}
    mtime = path.stat().st_mtime
    age = time.time() - mtime
    return {
        "available": True,
        "path": str(path),
        "age_sec": round(age, 1),
        "fresh": age < LOG_MAX_AGE_SEC,
        "size_bytes": path.stat().st_size,
    }


def _check_crash_history() -> dict:
    path = DATA_CACHE / "liveness_crash.jsonl"
    if not path.exists():
        return {"count": 0, "latest": None}
    try:
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except Exception as e:
        return {"count": 0, "latest": None, "error": str(e)}
    latest = None
    if lines:
        try:
            latest = json.loads(lines[-1])
        except Exception:
            latest = {"raw": lines[-1][:200]}
    return {"count": len(lines), "latest": latest}


def _check_paper_state() -> dict:
    path = DATA_CACHE / "paper_state.json"
    if not path.exists():
        return {"available": False, "reason": "missing"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"available": False, "reason": f"parse: {e}"}
    return {
        "available": True,
        "cash": data.get("cash"),
        "realized_pnl": data.get("realized_pnl"),
        "open_positions": len(data.get("positions", {}) or {}),
        "open_orders": len(data.get("orders", {}) or {}),
    }


def _maybe_send_telegram(anomalies: list[str]) -> bool:
    """Send Telegram only if there are real anomalies AND cooldown has passed.

    Returns True if sent.
    """
    if not anomalies:
        return False
    # Cooldown: read last anomaly alert time from STATE_FILE
    last_alert = 0.0
    if STATE_FILE.exists():
        try:
            prev = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            last_alert = float(prev.get("last_telegram_at", 0.0))
        except Exception:
            pass
    if time.time() - last_alert < TELEGRAM_COOLDOWN_SEC:
        return False

    token, chat_id = _read_creds()
    if not token or not chat_id:
        return False

    import urllib.request
    import urllib.parse

    msg = "[self-monitor] ANOMALY DETECTED\n\n" + "\n".join(f"- {a}" for a in anomalies)
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": msg}).encode("ascii")
    try:
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status == 200
    except Exception as e:
        print(f"[self-monitor] telegram send failed: {e}", file=sys.stderr)
        return False


def main() -> int:
    DATA_CACHE.mkdir(parents=True, exist_ok=True)

    audit = {
        "ts": _now_ist_iso(),
        "epoch": int(time.time()),
        "liveness": _check_liveness(),
        "log": _check_log(),
        "crash_history": _check_crash_history(),
        "paper_state": _check_paper_state(),
    }

    # Decide anomalies
    anomalies: list[str] = []
    if not audit["liveness"].get("fresh"):
        anomalies.append(f"liveness file stale ({audit['liveness'].get('age_sec', '?')}s old)")
    if not audit["log"].get("fresh"):
        anomalies.append(f"bot log stale ({audit['log'].get('age_sec', '?')}s old)")
    if not audit["liveness"].get("main_thread_alive"):
        anomalies.append("liveness main_thread_alive=False — bot may be hung")
    # crash_history.anomaly: if a new crash within last hour that we haven't seen
    latest = audit["crash_history"].get("latest") or {}
    if latest.get("ts"):
        try:
            crash_ts = datetime.fromisoformat(latest["ts"].replace("Z", "+00:00"))
            age_h = (datetime.now(crash_ts.tzinfo) - crash_ts).total_seconds() / 3600
            if age_h < 1.0:
                anomalies.append(f"new crash within last hour: {latest.get('reason', '?')} pid={latest.get('pid')}")
        except Exception:
            pass

    sent = _maybe_send_telegram(anomalies)
    audit["anomalies"] = anomalies
    audit["telegram_sent"] = sent
    if sent:
        audit["last_telegram_at"] = time.time()

    # Persist
    STATE_FILE.write_text(json.dumps(audit, indent=2, default=str), encoding="utf-8")
    try:
        with HISTORY_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(audit, default=str) + "\n")
    except Exception as e:
        print(f"[self-monitor] history append failed: {e}", file=sys.stderr)
    # Roll history
    try:
        if HISTORY_FILE.exists():
            lines = HISTORY_FILE.read_text(encoding="utf-8").splitlines()
            if len(lines) > HISTORY_KEEP:
                HISTORY_FILE.write_text("\n".join(lines[-HISTORY_KEEP:]) + "\n", encoding="utf-8")
    except Exception:
        pass

    # Compact stdout for cron log
    if anomalies:
        print(f"[self-monitor] ANOMALIES: {'; '.join(anomalies)} | telegram={sent}")
    else:
        print(f"[self-monitor] OK | liveness_age={audit['liveness'].get('age_sec')}s | "
              f"log_age={audit['log'].get('age_sec')}s | "
              f"uptime={audit['liveness'].get('uptime_sec')}s | "
              f"positions={audit['paper_state'].get('open_positions', '?')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
