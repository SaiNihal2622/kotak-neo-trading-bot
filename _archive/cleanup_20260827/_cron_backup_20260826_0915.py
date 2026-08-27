"""Send a CRITICAL backup alert from the cron self-monitor (Mavis's own backup channel)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv("config/credentials.env")

from kotak_bot.alerts.telegram import TelegramAlerter

alerter = TelegramAlerter()
msg = (
    "[CRON BACKUP] Self-monitor flagged ANOMALY at 09:15 IST: "
    "new crash within last hour (pid=10536, signal=SIGINT, cycle=5583, crash_ts=08:34:54 IST). "
    "Self-monitor's own Telegram already fired (telegram_sent=true, 30-min cooldown). "
    "Current liveness OK: new pid=11580 uptime=2377s main_thread_alive=true tick=79 state=running, "
    "log fresh (17.1s, 39.6MB). "
    "Paper state: cash=100229, realized_pnl=229, open_positions=0, open_orders=320. "
    "Action: monitor; main loop respawned ~40 min ago, running normally. "
    "Note: 320 open_orders worth a glance next tick."
)
print(f"Enabled: {alerter.enabled}")
print(f"chat_id: {alerter._get_chat_id()}")
ok = alerter.critical(msg)
print(f"Send result: {ok}")
