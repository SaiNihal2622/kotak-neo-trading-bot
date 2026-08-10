"""Fetch Telegram chat_id by polling getUpdates.

Prerequisite: user must send at least one message to the bot first.
"""
import json
import urllib.request
import urllib.error
from pathlib import Path

LOG = open("telegram_setup.txt", "w", encoding="utf-8")
def o(m): LOG.write(m + "\n"); LOG.flush()

# load token from .env manually
env_path = Path("config/credentials.env")
token = None
for line in env_path.read_text(encoding="utf-8").splitlines():
    if line.startswith("TELEGRAM_BOT_TOKEN="):
        token = line.split("=", 1)[1].strip()
        break

if not token:
    o("ERROR: TELEGRAM_BOT_TOKEN not found in config/credentials.env")
    raise SystemExit(1)

o(f"Bot token loaded: {token[:10]}...{token[-6:]}  ({len(token)} chars)")

# call getUpdates
url = f"https://api.telegram.org/bot{token}/getUpdates"
try:
    with urllib.request.urlopen(url, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    o(f"getUpdates response: ok={data.get('ok')}")
    if not data.get("ok"):
        o(f"Error: {data}")
    else:
        results = data.get("result", [])
        o(f"Found {len(results)} message(s) in inbox")
        if not results:
            o("")
            o("=" * 50)
            o("ACTION REQUIRED:")
            o("  1. Open Telegram on your phone")
            o("  2. Search for your bot (the one whose token is in .env)")
            o("  3. Send it any message, e.g. '/start' or 'hi'")
            o("  4. Re-run this script: python get_chat_id.py")
            o("=" * 50)
        else:
            for r in results:
                msg = r.get("message") or r.get("edited_message") or {}
                chat = msg.get("chat", {})
                chat_id = chat.get("id")
                chat_name = chat.get("first_name") or chat.get("title") or "(no name)"
                chat_type = chat.get("type")
                text = msg.get("text", "")
                o(f"  chat_id={chat_id}  name={chat_name}  type={chat_type}  msg='{text[:40]}'")
            if len(results) >= 1:
                chat_id = results[-1].get("message", {}).get("chat", {}).get("id")
                o("")
                o(f">>> YOUR CHAT_ID = {chat_id}")
                o(f">>> Add to config/credentials.env: TELEGRAM_CHAT_ID={chat_id}")
                # auto-append to .env if not present
                env_text = env_path.read_text(encoding="utf-8")
                if "TELEGRAM_CHAT_ID=" in env_text and "TELEGRAM_CHAT_ID=\n" in env_text or env_text.endswith("TELEGRAM_CHAT_ID="):
                    env_text = env_text.replace("TELEGRAM_CHAT_ID=", f"TELEGRAM_CHAT_ID={chat_id}")
                    env_path.write_text(env_text, encoding="utf-8")
                    o(">>> Auto-patched config/credentials.env")
except urllib.error.URLError as e:
    o(f"Network error: {e}")
except Exception as e:
    o(f"Error: {e}")

LOG.close()
