"""Check pending Telegram updates."""
import os
import json
from dotenv import load_dotenv
load_dotenv("config/credentials.env")
import httpx

token = os.getenv("TELEGRAM_BOT_TOKEN")
chat_id = int(os.getenv("TELEGRAM_CHAT_ID"))

with httpx.Client(timeout=10) as c:
    r = c.get(f"https://api.telegram.org/bot{token}/getUpdates?offset=-1&limit=100&timeout=2")
data = r.json()
print(f"ok={data.get('ok')}  count={len(data.get('result', []))}")
for u in data.get("result", []):
    msg = u.get("message") or {}
    frm = msg.get("from", {})
    is_user = not frm.get("is_bot")
    is_to_us = msg.get("chat", {}).get("id") == chat_id
    direction = "user_to_bot" if (is_user and is_to_us) else "bot_to_user" if (not is_user and is_to_us) else "other"
    text = msg.get("text", "")[:80]
    print(f"  [{direction}] {text}")
