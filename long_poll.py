"""Long-poll for 30s for any update on the bot."""
import json
import urllib.request
import urllib.parse

token = "8859774824:AAGCzAl1qDUnehmxHAHraMbT9S7id_C4lc8"

params = urllib.parse.urlencode({
    "timeout": 30,
    "allowed_updates": json.dumps(["message", "channel_post", "edited_message", "callback_query", "inline_query"]),
    "limit": 100,
})
url = f"https://api.telegram.org/bot{token}/getUpdates?{params}"

print(f"Long-polling {url[:100]}...")
try:
    with urllib.request.urlopen(url, timeout=45) as r:
        data = json.loads(r.read().decode("utf-8"))
    print(f"ok={data.get('ok')}  count={len(data.get('result', []))}")
    if data.get("result"):
        for u in data["result"][:5]:
            print(f"--- update_id={u.get('update_id')} ---")
            for k, v in u.items():
                if k != "update_id":
                    print(f"  {k}: {str(v)[:200]}")
    else:
        print("No messages waiting. The bot has zero pending updates.")
except Exception as e:
    print(f"Error: {e}")
