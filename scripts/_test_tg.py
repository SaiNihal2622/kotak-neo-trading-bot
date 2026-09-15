#!/usr/bin/env python
"""Test telegram directly."""
import sys, os
from pathlib import Path
ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
for line in (ROOT / 'config' / 'credentials.env').read_text(encoding='utf-8').splitlines():
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, v = line.split('=', 1)
        if k.strip() not in os.environ:
            os.environ[k.strip()] = v.strip().strip('"').strip("'")
import httpx
token = os.environ.get('TELEGRAM_BOT_TOKEN')
chat = os.environ.get('TELEGRAM_CHAT_ID')
print(f'token len={len(token) if token else 0}, chat={chat}')
r = httpx.post(f'https://api.telegram.org/bot{token}/sendMessage', json={'chat_id': chat, 'text': 'test from Mavis pre-market audit', 'parse_mode': 'HTML'}, timeout=8)
print('status', r.status_code, r.text[:200])
