#!/usr/bin/env python
"""Send overnight pre-market status to Telegram."""
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
msg = """[Mavis overnight 02:30] Pre-market prep for Thu 03-Sep-2026 (you can sleep)

SYSTEM STATUS — ALL GREEN
  Bot:      PID 10324, uptime 9.9h, tick 1098, thread OK, 0 positions
  Brain:    PID 21904 (just restarted fresh), tick 6466, 24/7 mode live
  Dashboard :8504  HTTP 200
  Audit:    PASSED (8/8 green, 1 informational warning)
  Lint:     PASSED (no shadow imports)
  Cash:     Rs.1,00,000 | Realized: Rs.0 | Positions: 0

KOTAK SESSION — re-authed at 02:30
  expires 08:29 IST (in 5.99 h) — covers 08:15 brief + 08:25 maintenance
  auto re-auth via session_watch in brain every 5 min if needed

BRAIN 24/7 MODE
  Active since yesterday. Each event in global_state.json triggers LLM
  Every 90 min periodic scan (works regardless of NSE hours)
  Every 2h overnight research (when NSE closed) analyzes US/Asia/crypto
  16 global instruments monitored live: SPX, NASDAQ, DOW, VIX, NIKKEI,
  HANGSENG, GOLD, WTI, BTC, ETH, DXY, USDINR, sector ETFs (XLF/XLK/XLE)

WHAT WILL HAPPEN AUTOMATICALLY (NO ACTION NEEDED)
  08:15 IST  - morning brief to Telegram (thesis + US close + VIX)
  08:25 IST  - daily maintenance (re-auth + self-test) - belt + suspenders
  08:30 IST  - NSSM (KotakBotPaper) re-auths if needed
  09:15 IST  - market opens, bot ready with fixed code
  09:15-13:30 - brain active in trading mode, can issue OPENs
  13:30 IST  - bot blocks new entries (intraday cutoff)
  14:30 IST  - bot force-squares all open positions
  15:30 IST  - market closes, bot continues to monitor
  15:35 IST  - daily post-mortem to Telegram
  15:45 IST  - state backup to Telegram
  17:30 IST  - post-EOD health check to Telegram

TOMORROW'S BRAIN WILL (24/7 + new fixes)
  - Use SENSEX as entry target (not just confirmation)
  - Recognize slow drift in low-vol (VIX < 12) as valid signal
  - Time-of-day gate: best entries 09:30-12:30
  - All 4 critical bugs fixed (Order UnboundLocalError, qty 75x, cap keys, pre-open consume)
  - LLM prompt: explicit qty=1 (one lot) convention
  - 3 shadow-import sites cleaned from __main__.py
  - Production audit + shadow lint run as defense in depth

GOOD NIGHT - 6.5h to market open, system is autonomous."""
r = a.send(msg)  # no parse_mode
print('sent' if r else 'failed')
