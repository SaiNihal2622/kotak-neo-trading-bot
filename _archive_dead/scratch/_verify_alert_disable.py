import sys
sys.path.insert(0, '.')
from kotak_bot.alerts.telegram import TelegramAlerter
a = TelegramAlerter(enabled=False)
print(f'alerter.enabled = {a.enabled}')
token_first = a.bot_token[:10] if a.bot_token else 'empty'
print(f'alerter.bot_token (first 10 chars) = {token_first}')
result = a.send('test message')
print(f'send result: {result}')
