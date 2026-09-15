#!/usr/bin/env python
import sys, os
from pathlib import Path
ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
sys.path.insert(0, str(ROOT / 'scripts'))
for line in (ROOT / 'config' / 'credentials.env').read_text(encoding='utf-8').splitlines():
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, v = line.split('=', 1)
        if k.strip() not in os.environ:
            os.environ[k.strip()] = v.strip().strip('"').strip("'")
print('env token:', os.environ.get('TELEGRAM_BOT_TOKEN', 'MISSING')[:10])
from telegram_alerter import get_alerter
a = get_alerter()
print('alerter:', a, 'enabled:', a.enabled if a else None)
if a:
    print('bot_token[:10]:', a.bot_token[:10])
    print('chat_id:', a._get_chat_id())
    print('send test:', a.send('test from Mavis pre-market audit', parse_mode='HTML'))
