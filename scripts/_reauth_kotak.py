#!/usr/bin/env python
"""One-shot re-auth of Kotak Neo session. Writes fresh data_cache/kotak_prod_session.json."""
import sys, json, time, os
from pathlib import Path
ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
sys.path.insert(0, str(ROOT))
# Load env
for line in (ROOT / 'config' / 'credentials.env').read_text(encoding='utf-8').splitlines():
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, v = line.split('=', 1)
        if k.strip() not in os.environ:
            os.environ[k.strip()] = v.strip().strip('"').strip("'")
from kotak_bot.data.kotak_prod_feed import KotakProdFeed
f = KotakProdFeed(
    env=os.environ.get('KOTAK_ENV', 'uat'),
    access_token=os.environ['KOTAK_API_KEY'],
    mobile=os.environ['KOTAK_MOBILE'],
    ucc=os.environ['KOTAK_UCC'],
    totp_secret=os.environ['KOTAK_TOTP_SECRET'],
    mpin=os.environ['KOTAK_MPIN'],
    poll_interval_sec=2.0,
)
ok = f._auth()
print(f'auth ok: {ok}')
sess = json.loads((ROOT / 'data_cache' / 'kotak_prod_session.json').read_text())
exp = sess.get('expires_at', 0)
hours = (exp - time.time()) / 3600
print(f'new expires_at: {hours:.2f}h from now')
