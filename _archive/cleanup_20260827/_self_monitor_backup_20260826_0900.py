"""Send CRITICAL backup alert for the 09:00 IST self-monitor tick."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv("config/credentials.env")

from kotak_bot.alerts.telegram import TelegramAlerter

alerter = TelegramAlerter()
msg = (
    "[CRON BACKUP] Self-monitor flagged ANOMALY at 09:00 IST: "
    "new crash within last hour (pid=10536, signal=SIGINT, cycle=5583, ts=2026-08-26T08:34:54+05:30). "
    "Self-monitor's own Telegram did NOT fire (telegram_sent=false, primary suppressed — likely cooldown). "
    "Current liveness OK: pid=11580 uptime=1503.5s (25m) main_thread_alive=true, log fresh (1.3s), "
    "paper_state cash=100229 realized_pnl=229 open_positions=0 open_orders=320. "
    "Action: monitor; SIGINT is clean shutdown (likely wake-task restart), main loop respawned and running normally."
)
print(f"Enabled: {alerter.enabled}")
print(f"chat_id: {alerter._get_chat_id()}")
ok = alerter.send(f"🚨 {msg}")
print(f"Send result: {ok}")
