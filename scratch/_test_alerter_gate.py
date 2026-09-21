"""Verify the universal TelegramAlerter gate works."""
import sys
sys.path.insert(0, '.')

from kotak_bot.alerts.telegram import TelegramAlerter

a = TelegramAlerter()
print(f'default call:     enabled={a.enabled}, source={a._enabled_source}')

b = TelegramAlerter(enabled=True)
print(f'explicit True:    enabled={b.enabled}, source={b._enabled_source}')

c = TelegramAlerter(enabled=False)
print(f'explicit False:   enabled={c.enabled}, source={c._enabled_source}')

print()
print('Expected (settings.yaml has alerts.telegram.enabled=false):')
print('  default call: enabled=False, source=settings.yaml')
print('  explicit True: enabled=True, source=explicit')
print('  explicit False: enabled=False, source=explicit')
