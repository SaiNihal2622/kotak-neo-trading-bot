"""Quant watchdog - keeps the quant_service alive without admin.

Runs as a background process. Every 60s:
1. Checks if quant_service is responding on :8503
2. If not, starts a new instance
3. Telegram-alerts on restarts (rate-limited)

The watchdog is the failsafe when NSSM is not available (no admin).
Itself runs as a regular process started via Start-Process -WindowStyle Hidden.
"""
from __future__ import annotations

import os
import sys
import time
import signal
import subprocess
import threading
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from loguru import logger

ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
LOG = ROOT / 'data_cache' / 'quant_watchdog.log'
ENV_PATH = ROOT / 'config' / 'credentials.env'
SERVICE_HTTP = 'http://127.0.0.1:8503'
SERVICE_HEALTH = f'{SERVICE_HTTP}/health'
PY = str(ROOT / '.venv' / 'Scripts' / 'python.exe')
SCRIPT = str(ROOT / 'scripts' / 'quant_service.py')
CHECK_INTERVAL_SEC = 30
RESTART_COOLDOWN_SEC = 120  # don't restart more than once per 2min
TELEGRAM_COOLDOWN_SEC = 300

last_restart = 0
last_tg_alert = 0
RUNNING = True


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec='seconds')


def log(msg: str) -> None:
    line = f"[{now_iso()}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_env() -> dict:
    env = {}
    for line in ENV_PATH.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def send_telegram(msg: str) -> None:
    env = load_env()
    token = env.get('TELEGRAM_BOT_TOKEN', '')
    chat = env.get('TELEGRAM_CHAT_ID', '')
    if not token or not chat:
        return
    try:
        httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": msg, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=8,
        )
    except Exception:
        pass


def is_service_alive() -> bool:
    try:
        r = httpx.get(SERVICE_HEALTH, timeout=5)
        return r.status_code == 200 and r.json().get('ok') is True
    except Exception:
        return False


def start_service() -> int:
    log("start_service: launching quant_service")
    try:
        p = subprocess.Popen(
            [PY, '-u', SCRIPT],
            cwd=str(ROOT),
            stdout=open(ROOT / 'Logs' / 'quant_service.out.log', 'a'),
            stderr=open(ROOT / 'Logs' / 'quant_service.err.log', 'a'),
            creationflags=0x08000000,  # DETACHED_PROCESS on Windows
        )
        log(f"start_service: launched PID {p.pid}")
        return p.pid
    except Exception as e:
        log(f"start_service: err {e}")
        return 0


def signal_handler(sig, frame):
    global RUNNING
    log(f"SHUTDOWN: signal {sig}")
    RUNNING = False


def main() -> int:
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    log(f"QUANT-WATCHDOG: starting (pid={os.getpid()})")

    global last_restart, last_tg_alert
    consecutive_dead = 0
    while RUNNING:
        try:
            alive = is_service_alive()
            if alive:
                if consecutive_dead > 0:
                    log(f"RECOVERED: service is alive again (was dead for {consecutive_dead} checks)")
                    consecutive_dead = 0
                time.sleep(CHECK_INTERVAL_SEC)
                continue

            consecutive_dead += 1
            log(f"DEAD: service not responding (consecutive={consecutive_dead})")

            now = time.time()
            if (now - last_restart) < RESTART_COOLDOWN_SEC:
                log(f"cooldown: skipping restart (last {int(now - last_restart)}s ago)")
                time.sleep(CHECK_INTERVAL_SEC)
                continue

            log("RESTART: launching new quant_service instance")
            pid = start_service()
            last_restart = now

            if (now - last_tg_alert) > TELEGRAM_COOLDOWN_SEC:
                send_telegram(f"<b>[Quant watchdog]</b> Service was down, restarted. PID={pid}")
                last_tg_alert = now

            time.sleep(CHECK_INTERVAL_SEC)
        except Exception as e:
            log(f"LOOP-ERR: {e}")
            time.sleep(5)

    log("QUANT-WATCHDOG: stopped")
    return 0


if __name__ == '__main__':
    sys.exit(main())
