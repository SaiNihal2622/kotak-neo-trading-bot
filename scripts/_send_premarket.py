#!/usr/bin/env python
"""Send pre-market readiness report to Telegram."""
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
msg = """[Mavis 06:11] Pre-market readiness check (Wed 02-Sep-2026)

BOT
  PID 14612, paper mode, capital Rs.1,09,978, realized +Rs.9,978
  Tick 1062, subscribed NIFTY+BNF, data_source=live_kotak
  Risk caps: 1% per-trade scale-down, 5% per-position, max 6 positions
  No errors in last 1h (1 transient TimeoutError self-recovered)

BRAIN (quant_service on :8503)
  PID 7436 (NSSM), tick 1255, last decision 06:00 IST HOLD (post-mkt)
  HTTP self-restart wired (5-60s backoff)
  8 in-process schedulers active (08:15 brief, 08:25 daily-maint, 09:00 news, 14:50 closing-straddle, 15:45 EOD backup, Sun 18:00 weekly, Sun 21:00 weekend-intel, 23:00 nightly-improvement)
  4 modules wired: backtest, oi_change_detector, telegram_alerter, session_watch
  Session watcher: every 5min, auto re-auth at expiry

KOTAK SESSION
  Just re-authed: 6h fresh (expires 12:10 IST)
  env=uat, base=https://e22.kotaksecurities.com

SHELL STARTUP (5 scripts)
  KotakBotPaper.bat, KotakLiveDashboard.bat, KotakQuantService.bat, mavis_app_wrapper.vbs, supervisor_wrapper.vbs

VIX 11.19 (calm regime, no edge if range-bound)

DASHBOARD :8504 alive (4 candles NIFTY/BNF/FIN/SENSEX + 5-row spot table + VIX card + session pill + data-age)

DASHBOARD JS will be updated next to render SENSEX/FINNIFTY candles + new spot table + VIX card. Will commit+push.

Ready for 09:15 open."""
r = a.send(msg, parse_mode='HTML')
print('sent' if r else 'failed')
