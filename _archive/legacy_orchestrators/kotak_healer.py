"""Kotak Healer — self-healing watchdog for the kotak_bot paper process.

Runs as a background process. Every CHECK_INTERVAL seconds it:
  1. Checks if `python -m kotak_bot paper` is alive (process + dashboard 200)
  2. If dead during market hours, restarts it via start_bot_detached.ps1
  3. Sends a Telegram alert on state-change (with cooldown to avoid spam)
  4. Logs every check to data_cache/healer.log
  5. Persists health state to data_cache/healer_state.json

This is the "self-healing" layer. It does NOT touch the bot's code or
state — it only manages the bot's lifecycle.

CLI:
  python kotak_healer.py --once    # run a single check, exit
  python kotak_healer.py            # loop forever (use as background process)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(ROOT))

from loguru import logger  # noqa: E402

HEALER_STATE_PATH = ROOT / "data_cache" / "healer_state.json"
HEALER_LOG_PATH = ROOT / "data_cache" / "healer.log"
BOT_LOG_PATH = ROOT / "Logs" / "bot.log"
DASHBOARD_URL = "http://localhost:8501"
START_SCRIPT = ROOT / "start_bot_detached.ps1"
BOT_CMDLINE_FRAGMENT = "kotak_bot"  # used to find the running python process

CHECK_INTERVAL_SEC = 60
RESTART_COOLDOWN_SEC = 180       # don't restart more than once per 3 min
ALERT_COOLDOWN_SEC = 300         # don't send telegram more than once per 5 min
STALE_LOG_SEC = 600              # 10 min — log must be touched within this
STARTUP_GRACE_SEC = 120          # 2 min after restart, expect false-negative

# cache state
_last_restart_at: float = 0.0
_last_alert_at: float = 0.0
_session_start: float = 0.0


# -------- helpers --------

def _is_market_hours() -> bool:
    try:
        from kotak_bot.utils.clock import now_ist, market_session
        return market_session(now_ist()) in ("pre_open", "opening", "regular", "closing")
    except Exception:
        # fallback: 09:00–15:30 IST Mon–Fri
        from datetime import datetime, time, timezone, timedelta
        IST = timezone(timedelta(hours=5, minutes=30))
        n = datetime.now(IST)
        if n.weekday() >= 5:
            return False
        return time(9, 0) <= n.time() <= time(15, 30)


def _bot_process_alive() -> tuple[bool, list[int]]:
    """Return (alive, pids). Looks for `python -m kotak_bot ...` in tasklist."""
    pids: list[int] = []
    try:
        out = subprocess.run(
            ["wmic", "process", "where",
             "name='python.exe'", "get", "ProcessId,CommandLine", "/FORMAT:CSV"],
            capture_output=True, text=True, timeout=15,
        )
        if out.returncode != 0:
            return False, []
        for line in out.stdout.splitlines():
            if BOT_CMDLINE_FRAGMENT in line and "kotak_healer" not in line and "kotak_brain" not in line:
                # CSV format: Node,CommandLine,ProcessId
                parts = line.strip().split(",")
                if len(parts) >= 3:
                    try:
                        pids.append(int(parts[-1]))
                    except ValueError:
                        pass
    except Exception as e:
        logger.warning(f"healer: wmic failed: {e}")
        return False, []
    return len(pids) > 0, pids


def _dashboard_alive() -> bool:
    try:
        import httpx
        r = httpx.get(DASHBOARD_URL, timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def _log_fresh() -> bool:
    try:
        if not BOT_LOG_PATH.exists():
            return False
        mtime = BOT_LOG_PATH.stat().st_mtime
        return (time.time() - mtime) < STALE_LOG_SEC
    except Exception:
        return False


def _send_telegram(text: str) -> bool:
    """Best-effort telegram send via the existing TelegramAlerter."""
    global _last_alert_at
    if (time.time() - _last_alert_at) < ALERT_COOLDOWN_SEC:
        logger.debug(f"healer: telegram suppressed (cooldown); msg={text[:60]}")
        return False
    try:
        # Reuse the bot's telegram module if available
        from kotak_bot.alerts.telegram import TelegramAlerter
        alerter = TelegramAlerter()
        ok = alerter.send(text)
        if ok:
            _last_alert_at = time.time()
        return ok
    except Exception as e:
        logger.debug(f"healer: telegram send failed: {e}")
        return False


def _restart_bot() -> bool:
    """Restart the bot via start_bot_detached.ps1. Respects cooldown."""
    global _last_restart_at
    if (time.time() - _last_restart_at) < RESTART_COOLDOWN_SEC:
        logger.info(f"healer: restart suppressed (cooldown); last={_last_restart_at:.0f}")
        return False
    if not START_SCRIPT.exists():
        logger.error(f"healer: start script missing: {START_SCRIPT}")
        return False
    try:
        # Use PowerShell to start the bot detached. -WindowStyle Hidden to avoid popup.
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-File", str(START_SCRIPT)],
            capture_output=True, text=True, timeout=60,
        )
        if out.returncode == 0:
            _last_restart_at = time.time()
            logger.info(f"healer: restart triggered (rc={out.returncode})")
            return True
        else:
            logger.error(f"healer: restart failed rc={out.returncode}: {out.stderr[:200]}")
            return False
    except Exception as e:
        logger.exception(f"healer: restart exception: {e}")
        return False


def _load_state() -> dict:
    try:
        if HEALER_STATE_PATH.exists():
            with open(HEALER_STATE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"healer: could not load state: {e}")
    return {}


def _save_state(state: dict) -> None:
    try:
        HEALER_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = HEALER_STATE_PATH.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        tmp.replace(HEALER_STATE_PATH)
    except Exception as e:
        logger.error(f"healer: could not save state: {e}")


# -------- main check --------

def check_once() -> dict:
    """Run a single health check. Returns the state dict (also persisted)."""
    state = _load_state()
    prev_alive = bool(state.get("alive", False))
    market_hours = _is_market_hours()
    proc_alive, pids = _bot_process_alive()
    dash_alive = _dashboard_alive()
    log_fresh = _log_fresh()

    # Anomaly detection:
    #   During market hours: dead process OR dead dashboard = ANOMALY
    #   Outside market hours: dead process alone is FINE (we don't keep it up 24/7
    #   to save CPU/memory; the start_bot script only runs during market hours)
    is_anomaly = False
    reason = ""
    if market_hours and (not proc_alive or not dash_alive):
        is_anomaly = True
        reasons = []
        if not proc_alive:
            reasons.append("process dead")
        if not dash_alive:
            reasons.append("dashboard down")
        if not log_fresh:
            reasons.append("log stale")
        reason = ", ".join(reasons)

    # Decide if we should restart
    should_restart = is_anomaly and (time.time() - _last_restart_at) >= RESTART_COOLDOWN_SEC

    state.update({
        "alive": proc_alive and dash_alive,
        "pids": pids,
        "market_hours": market_hours,
        "dashboard_alive": dash_alive,
        "log_fresh": log_fresh,
        "is_anomaly": is_anomaly,
        "reason": reason,
        "last_check": datetime.utcnow().isoformat() + "Z",
        "last_restart_at": state.get("last_restart_at"),
        "total_restarts": int(state.get("total_restarts", 0)),
    })

    if should_restart:
        ok = _restart_bot()
        if ok:
            state["last_restart_at"] = datetime.utcnow().isoformat() + "Z"
            state["total_restarts"] = int(state.get("total_restarts", 0)) + 1
            _send_telegram(
                f"🔧 Kotak Healer: bot was down ({reason}). Restarted. "
                f"Total restarts today: {state['total_restarts']}"
            )
    elif is_anomaly:
        logger.warning(f"healer: anomaly but restart suppressed (cooldown): {reason}")
    elif not prev_alive and proc_alive and dash_alive:
        # recovered
        _send_telegram("✅ Kotak Healer: bot recovered (process + dashboard back).")

    _save_state(state)
    status = "OK" if not is_anomaly else f"ANOMALY ({reason})"
    logger.info(
        f"healer: market={market_hours} proc={proc_alive}(pids={pids}) "
        f"dash={dash_alive} log_fresh={log_fresh} -> {status}"
    )
    return state


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Run a single check then exit")
    parser.add_argument("--interval", type=int, default=CHECK_INTERVAL_SEC,
                        help=f"Check interval in seconds (default {CHECK_INTERVAL_SEC})")
    args = parser.parse_args()

    HEALER_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logger.add(str(HEALER_LOG_PATH), rotation="1 day", retention="14 days", level="INFO")

    logger.info(f"healer: starting (once={args.once} interval={args.interval}s)")

    if args.once:
        check_once()
        return 0

    # graceful shutdown on SIGINT
    import signal
    stop = False

    def _sigint(_sig, _frm):
        nonlocal stop
        stop = True
        logger.info("healer: SIGINT, shutting down")
    try:
        signal.signal(signal.SIGINT, _sigint)
    except Exception:
        pass

    while not stop:
        try:
            check_once()
        except Exception as e:
            logger.exception(f"healer: check error: {e}")
        # sleep in small chunks so SIGINT is responsive
        for _ in range(args.interval):
            if stop:
                break
            time.sleep(1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
