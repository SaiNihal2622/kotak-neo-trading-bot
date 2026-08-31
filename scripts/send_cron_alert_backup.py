"""Send a CRITICAL backup alert from the cron self-monitor (Mavis's own backup channel)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv("config/credentials.env")

from kotak_bot.alerts.telegram import TelegramAlerter

alerter = TelegramAlerter()
msg = (
    "[CRON BACKUP] Self-monitor flagged ANOMALY at 20:15 IST: "
    "new crash within last hour (pid=10124, signal=SIGINT, cycle=14274). "
    "Self-monitor's own Telegram did NOT fire (telegram_sent=false, primary suppressed). "
    "Current liveness OK: new pid=2444 uptime=1083s main_thread_alive=true, log fresh (30.1s). "
    "Action: monitor; main loop has respawned and is running normally."
)
print(f"Enabled: {alerter.enabled}")
print(f"chat_id: {alerter._get_chat_id()}")
ok = alerter.send(f"🚨 {msg}")
print(f"Send result: {ok}")
