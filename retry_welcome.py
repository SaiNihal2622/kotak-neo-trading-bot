"""Retry welcome with plain text and get the error details."""
import json
import urllib.request
import urllib.error

token = "8859774824:AAGCzAl1qDUnehmxHAHraMbT9S7id_C4lc8"
chat_id = 8537408638

url = f"https://api.telegram.org/bot{token}/sendMessage"
# Plain text, no markdown
payload = json.dumps({
    "chat_id": chat_id,
    "text": "Kotak Neo Trading Bot connected. chat_id 8537408638 saved. Bot is running in paper mode. Dashboard: http://localhost:8501",
}).encode("utf-8")
req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
try:
    with urllib.request.urlopen(req, timeout=10) as r:
        resp = json.loads(r.read().decode("utf-8"))
    print(f"ok={resp.get('ok')}")
    print(f"response: {json.dumps(resp, indent=2)[:500]}")
except urllib.error.HTTPError as e:
    body = e.read().decode("utf-8")
    print(f"HTTPError {e.code}: {body}")
except Exception as e:
    print(f"Error: {e}")
