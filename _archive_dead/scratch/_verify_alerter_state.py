"""Reproduce what the bot does at startup, then dump the alerter's enabled state."""
import sys
sys.path.insert(0, '.')
import yaml

# Load config exactly as bot does
cfg = yaml.safe_load(open('config/settings.yaml'))

# Reproduce the bot's TelegramAlerter construction
from kotak_bot.alerts.telegram import TelegramAlerter

_tg_cfg = cfg.get('alerts', {}).get('telegram', {}) or {}
_tg_enabled = bool(_tg_cfg.get('enabled', False))
print(f'settings.yaml alerts.telegram.enabled = {_tg_cfg.get("enabled")!r}')
print(f'_tg_enabled (computed) = {_tg_enabled}')

alerter = TelegramAlerter(
    voice_enabled=cfg.get('alerts', {}).get('voice', {}).get('enabled', True),
    enabled=_tg_enabled,
)
print(f'\nalerter.enabled = {alerter.enabled}')
print(f'alerter.bot_token[:10] = {alerter.bot_token[:10] if alerter.bot_token else "<empty>"}')

# Now mimic the call path from self_heal.py:487
result = alerter.send('test from __main__ path')
print(f'alerter.send() returned: {result}')

# Also test send_photo (which has its own check) and send_voice
import tempfile
with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
    tmp = f.name
result = alerter.send_photo(tmp, caption='test photo')
print(f'alerter.send_photo() returned: {result}')

result = alerter.send_voice(tmp, caption='test voice')
print(f'alerter.send_voice() returned: {result}')
