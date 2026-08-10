"""Verify the exact bot identity."""
import json
import urllib.request

token = "8859774824:AAGCzAl1qDUnehmxHAHraMbT9S7id_C4lc8"
with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/getMe", timeout=10) as r:
    me = json.loads(r.read().decode("utf-8"))["result"]

print("EXACT bot you need to message:")
print(f"  Display name: {me['first_name']}")
print(f"  Username:     @{me['username']}")
print(f"  Bot ID:       {me['id']}")
print()
print("Search steps in Telegram:")
print("  1. Open Telegram, tap the SEARCH icon (top)")
print("  2. Type EXACTLY: @Kotak_Neo_Bot   (with the underscore)")
print("  3. The result should show: 'Kotak Neo Bot' with the username @Kotak_Neo_Bot")
print("  4. Tap on it, then tap START (or just type any message)")
print()
print("If you don't see 'Kotak Neo Bot' / @Kotak_Neo_Bot in the search,")
print("you may have created a different bot. Let me know and I'll fix it.")
