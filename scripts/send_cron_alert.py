"""Send a CRITICAL backup alert from the cron self-monitor (Mavis's own backup channel)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv("config/credentials.env")

from kotak_bot.alerts.telegram import TelegramAlerter

alerter = TelegramAlerter()
msg = (
    "[CRON BACKUP] Self-monitor flagged ANOMALY at 18:45 IST: "
    "new crash within last hour (pid=10032, signal=SIGINT, cycle=4255). "
    "Self-monitor's own Telegram already fired (telegram_sent=true, 30-min cooldown). "
    "Current liveness OK: new pid=7072 uptime=361s main_thread_alive=true, log fresh (2.1s). "
    "Action: monitor; http_server respawned gracefully ~6 min ago."
)
print(f"Enabled: {alerter.enabled}")
print(f"chat_id: {alerter._get_chat_id()}")
ok = alerter.critical(msg)
print(f"Send result: {ok}")
