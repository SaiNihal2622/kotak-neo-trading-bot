"""Background watcher for Telegram chat_id.

Polls getUpdates every 10s. When the user messages the bot, auto-patches
config/credentials.env with TELEGRAM_CHAT_ID=<id> and exits.

Run with: python telegram_auto_watch.py  (in background, will exit when chat_id found)
"""
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

LOG = open("telegram_watch.log", "w", encoding="utf-8")
def o(m):
    line = f"[{time.strftime('%H:%M:%S')}] {m}"
    LOG.write(line + "\n")
    LOG.flush()
    # also print, but suppress Unicode
    try:
        print(line)
    except UnicodeEncodeError:
        pass

env_path = Path("config/credentials.env")
token = None
for line in env_path.read_text(encoding="utf-8").splitlines():
    if line.startswith("TELEGRAM_BOT_TOKEN="):
        token = line.split("=", 1)[1].strip()
        break

if not token:
    o("FATAL: TELEGRAM_BOT_TOKEN not in .env")
    sys.exit(1)

o(f"Watching for messages to bot {token[:10]}... (poll every 10s)")

last_update_id = None
while True:
    try:
        url = f"https://api.telegram.org/bot{token}/getUpdates"
        if last_update_id is not None:
            url += f"?offset={last_update_id + 1}"
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if not data.get("ok"):
            o(f"Telegram error: {data}")
            time.sleep(10)
            continue
        results = data.get("result", [])
        for r in results:
            last_update_id = r.get("update_id", last_update_id)
            msg = r.get("message") or r.get("edited_message") or {}
            chat = msg.get("chat", {})
            chat_id = chat.get("id")
            if not chat_id:
                continue
            chat_name = chat.get("first_name") or chat.get("title") or "(no name)"
            text = msg.get("text", "")
            o(f">>> GOT MESSAGE: chat_id={chat_id}  from={chat_name}  text='{text[:60]}'")
            # patch .env
            env_text = env_path.read_text(encoding="utf-8")
            new_line = f"TELEGRAM_CHAT_ID={chat_id}"
            if "TELEGRAM_CHAT_ID=" in env_text:
                # replace existing empty value
                import re
                env_text = re.sub(r"TELEGRAM_CHAT_ID=.*", new_line, env_text)
            else:
                env_text = env_text.rstrip() + "\n" + new_line + "\n"
            env_path.write_text(env_text, encoding="utf-8")
            o(f">>> PATCHED config/credentials.env with TELEGRAM_CHAT_ID={chat_id}")
            # also send a confirmation message
            try:
                send_url = f"https://api.telegram.org/bot{token}/sendMessage"
                payload = json.dumps({
                    "chat_id": chat_id,
                    "text": (
                        "✅ Connected to Kotak Neo Trading Bot\n\n"
                        "Chat ID saved. You'll get alerts on every entry/exit/error here.\n\n"
                        f"Your chat_id: `{chat_id}`\n"
                        "Bot status: ready to trade on UAT"
                    ),
                }).encode("utf-8")
                req = urllib.request.Request(send_url, data=payload, headers={"Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=10).read()
                o(">>> Sent confirmation to user")
            except Exception as e:
                o(f"Send confirmation failed: {e}")
            o("DONE — chat_id acquired. Exiting watcher.")
            LOG.close()
            sys.exit(0)
        if not results:
            # heartbeat every minute
            if int(time.time()) % 60 < 10:
                o("(still watching — no messages yet)")
        time.sleep(10)
    except KeyboardInterrupt:
        o("Interrupted — exiting")
        break
    except Exception as e:
        o(f"Error: {e}")
        time.sleep(10)

LOG.close()
