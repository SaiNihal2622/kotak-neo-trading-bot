#!/usr/bin/env python
"""Final overnight status — sent when user goes to sleep."""
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
from telegram_alerter import get_alerter
a = get_alerter()
if not a or not a.enabled:
    print('alerter disabled')
    sys.exit(1)
msg = """[Mavis 02:42] Overnight pre-market prep complete — you can sleep

SYSTEM READY FOR 09:15 IST THU 03-SEP
  Bot:        PID 10324, uptime 10h, tick 1100+, thread alive, 0 positions
  Brain:      PID 12480, tick 6695, 24/7 mode loaded
  Dashboard:  :8504 HTTP 200
  Audit:      PASSED (8/8)
  Lint:       PASSED (no shadow imports)
  Cash:       Rs.1,00,000 | Realized: Rs.0 | Positions: 0

KOTAK SESSION
  re-authed at 02:30 IST
  expires 08:29 IST (in 5.78 h) — covers 08:15 brief + 08:25 maintenance

WHAT WILL HAPPEN AUTOMATICALLY (NO ACTION NEEDED)
  08:15 IST  - morning brief to Telegram (US close + VIX + thesis)
  08:25 IST  - daily maintenance (re-auth + self-test)
  08:30 IST  - NSSM (KotakBotPaper) re-auths if needed
  09:15 IST  - market opens, bot ready with fixed code
  09:15-13:30 - brain active in trading mode
  13:30 IST  - bot blocks new entries (intraday cutoff)
  14:30 IST  - bot force-squares all open positions
  15:30 IST  - market closes
  15:35 IST  - daily post-mortem to Telegram
  15:45 IST  - state backup to Telegram
  17:30 IST  - post-EOD health check
  23:00 IST  - nightly improvement (self-evolution)

OVERNIGHT GLOBAL STATE (live now)
  S&P 500: 7,666 (+0.46%) | NASDAQ: 26,217 (+0.45%) | DOW: 53,061 (+0.56%)
  VIX: 15.20 (-6.98% — risk-on signal for tomorrow)
  NIKKEI: 66,215 (flat)
  BTC-USD: $76,596 (-1.04%) | ETH-USD: $2,318 (-1.40%)
  Gold: 4,355 (+0.17%) | WTI: $68.50 (+0.5%)

SLEEP TIGHT
  6.5h to market open
  All 4 critical bugs fixed in source
  2 linters in place
  11 in-process schedulers ready
  Brain has the new prompt (SENSEX, low-vol, 13:30 cutoff)
  Bot has the fixed code (Order UnboundLocalError, qty clamp, cap keys)

Sleep well. The system runs itself."""
r = a.send(msg)
print('sent' if r else 'failed')
