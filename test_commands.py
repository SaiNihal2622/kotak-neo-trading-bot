"""Test the Telegram command handler by sending test commands."""
import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv
load_dotenv("config/credentials.env")

import urllib.request
import json
import httpx

token = os.getenv("TELEGRAM_BOT_TOKEN")
chat_id = os.getenv("TELEGRAM_CHAT_ID")

# Send a few test messages (simulating user typing /status, /pnl, /help)
commands = ["/status", "/pnl", "/regime", "/time", "/ping"]
for cmd in commands:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": int(chat_id), "text": cmd}
    with httpx.Client(timeout=10) as c:
        r = c.post(url, json=payload)
    print(f"Sent: {cmd}  -> status={r.status_code}")
    time.sleep(1)

# Wait a moment for the bot to receive and respond
print("Waiting 5s for bot to process commands...")
time.sleep(5)

# Now check getUpdates to see the bot's responses
url = f"https://api.telegram.org/bot{token}/getUpdates?timeout=5"
with urllib.request.urlopen(url, timeout=10) as r:
    data = json.loads(r.read().decode("utf-8"))

print(f"\nBot received {len(data.get('result', []))} messages total")
# Look for bot's responses (from_bot=True)
for u in data.get("result", [])[-15:]:
    msg = u.get("message") or {}
    if msg.get("from", {}).get("is_bot"):
        print(f"\n[Bot reply to {msg.get('reply_to_message', {}).get('text', '?')[:30]}]")
        print(f"  {msg.get('text', '')[:200]}")
    else:
        print(f"\n[User sent]: {msg.get('text', '')[:50]}")
