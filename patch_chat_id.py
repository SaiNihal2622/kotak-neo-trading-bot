"""Patch .env with the discovered chat_id and send a welcome message."""
import json
import urllib.request
from pathlib import Path

env_path = Path("config/credentials.env")
token = "8859774824:AAGCzAl1qDUnehmxHAHraMbT9S7id_C4lc8"
chat_id = 8537408638  # discovered by long poll

# 1. Patch .env
env_text = env_path.read_text(encoding="utf-8")
import re
env_text = re.sub(r"TELEGRAM_CHAT_ID=.*", f"TELEGRAM_CHAT_ID={chat_id}", env_text)
env_path.write_text(env_text, encoding="utf-8")
print(f"PATCHED {env_path}: TELEGRAM_CHAT_ID={chat_id}")

# 2. Send welcome message
welcome = (
    "✅ Kotak Neo Trading Bot is live!\n\n"
    f"Your chat_id: `{chat_id}`\n"
    "Saved to config. You'll get alerts here on every entry, exit, and error.\n\n"
    "Status right now:\n"
    "  • Bot: running (paper mode, synthetic feed)\n"
    "  • Kotak UAT: auth verified\n"
    "  • Dashboard: http://localhost:8501\n"
    "  • Market: closed (opens 9:00 AM IST)\n\n"
    "When market opens tomorrow, the bot will switch to live UAT data "
    "and start placing paper trades against real ticks."
)

url = f"https://api.telegram.org/bot{token}/sendMessage"
payload = json.dumps({
    "chat_id": chat_id,
    "text": welcome,
    "parse_mode": "Markdown",
}).encode("utf-8")
req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
try:
    with urllib.request.urlopen(req, timeout=10) as r:
        resp = json.loads(r.read().decode("utf-8"))
    print(f"Welcome sent: ok={resp.get('ok')}")
    if not resp.get("ok"):
        print(f"  Error: {resp}")
except Exception as e:
    print(f"Send failed: {e}")
