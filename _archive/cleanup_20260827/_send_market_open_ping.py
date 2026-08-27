"""Send 9:00 AM market-open Telegram ping."""
import requests

token = '8859774824:AAGCzAl1qDUnehmxHAHraMbT9S7id_C4lc8'
chat = '8537408638'

msg = """Good morning. Market just opened. Bot is in position. Today's plan:
- Regime detection running
- Strategy selector: trending \u2192 directional, range \u2192 iron condor
- Risk caps: 1% per trade, 3% daily
- Will alert on every entry/exit. Use /status anytime."""

try:
    r = requests.post(
        f'https://api.telegram.org/bot{token}/sendMessage',
        json={'chat_id': chat, 'text': msg, 'disable_web_page_preview': True},
        timeout=10,
    )
    print(f'Sent: {r.status_code} ok={r.json().get("ok")} desc={r.json().get("description","")}')
except Exception as e:
    print(f'Failed: {e}')
