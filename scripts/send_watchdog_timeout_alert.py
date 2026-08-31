"""Send a one-shot Telegram alert: HTTP server watchdog timed out at bash layer (120s).
Recovery status: HTTP server now healthy on :8502 (new PID 13056 spawned at 09:30:41 IST).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv("config/credentials.env")

from kotak_bot.alerts.telegram import TelegramAlerter

alerter = TelegramAlerter()
msg = (
    "[HTTP WATCHDOG] bash 120s timeout at 09:30 IST. "
    "Watchdog triggered restart: old PID 12532 replaced by new PID 13056 (age ~2 min). "
    "Post-timeout health check: port 8501=200 OK, port 8502=200 OK, liveness.available=true. "
    "No action required — auto-recovered."
)
print(f"Enabled: {alerter.enabled}")
print(f"chat_id: {alerter._get_chat_id()}")
ok = alerter.send(f"🚨 {msg}")
print(f"Send result: {ok}")
