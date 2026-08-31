"""Send a Telegram alert for the new session-hygiene FAIL detected at 10:10 IST."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv("config/credentials.env")

from kotak_bot.alerts.telegram import TelegramAlerter

alerter = TelegramAlerter()
msg = (
    "[HYGIENE] New FAIL detected at 10:10 IST: "
    "session mvs_4e4669276da7456e9455a7971d1071c0 (kotak-mavis-self-driver · 08-31 10:07) "
    "in error state — API error 715 (1000). Session was tiny (0.2MB, 2 messages, 37k tokens) "
    "so NOT a context-size issue; transient upstream API error. Already archived. "
    "Compaction-fail count last 7d: 9 (up from 8). "
    "Active sessions: 129 (down from 134 at 10:00). "
    "Action: monitor; cron will spawn a fresh self-driver session on next tick."
)
print(f"Enabled: {alerter.enabled}")
try:
    chat_id = alerter._get_chat_id()
    print(f"chat_id: {chat_id}")
except Exception as e:
    print(f"chat_id error: {e}")
ok = alerter.send(f"🚨 {msg}")
print(f"Send result: {ok}")
