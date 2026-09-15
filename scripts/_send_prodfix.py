#!/usr/bin/env python
"""Send production-grade hardening report to Telegram."""
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
msg = """[Mavis 12:30] PRODUCTION-GRADE HARDENING COMPLETE — 3 critical bugs fixed

PRODUCTION AUDIT INCIDENT (12:20 IST):
  Found 2 phantom positions in paper_state:
    NIFTY 23800 PE: qty=+5625 (75 lots!) avg=112.62
    NIFTY 23500 PE: qty=-5625 (75 lots!) avg=28.13
  Cash: -Rs.3,65,278 (deeply negative margin debt)

ROOT CAUSE #1: 5% cost cap silently disabled for 4 weeks
  - paper_client returns margin key 'available'
  - bot's __main__.py looked for 'available_cash'
  - .get('available_cash', 0) returned 0 -> cap bypassed

ROOT CAUSE #2: qty 75x oversized on every trade
  - Brain LLM was sending qty=75 thinking it meant 1 NIFTY lot
  - Bot multiplied by lot_size=75 to get 5625 shares
  - Combined with bug #1, every trade was 4-5x capital, no cap fired

ROOT CAUSE #3: bot auto-placement at 11:53 IST (after I restarted brain)
  - Brain issued bear_put_vertical OPEN (NIFTY 23800/23500 PE)
  - Bot placed both legs at 75 lots each = 5625 qty
  - No cap check (bug #1) + qty mis-interpretation (bug #2) = phantom positions

FIXES SHIPPED (8bde613 + 5b0149c on master):
  1. kotak_bot/__main__.py — cap reads from BOTH 'available' and 'available_cash'
  2. kotak_bot/__main__.py — MAX_LOTS_PER_LEG=10 hard cap on any brain leg
  3. kotak_bot/__main__.py — PHANTOM RECONCILE: at startup, scan for any position
     with qty > 50 lots, force-close at MARKET, send Telegram alert
  4. scripts/quant_service.py — _normalize_decision clamps leg qty to [1, 10]
  5. scripts/quant_service.py — LLM prompt explicitly says 'qty in LOTS, almost
     always qty=1; qty=75 = 75 lots = INSTANT REJECTION'
  6. scripts/production_audit.py — 8-check self-audit for daily/cron use
  7. watchdog.ps1 — REMOVED (was racing with NSSM bot)
  8. Orphan bot (Aug 27) — KILLED (was running pre-fix code)

CLEANUP:
  - Closed 2 phantom NIFTY positions at market
  - paper_state restored: cash Rs.1,00,000, 0 positions
  - audit log: data_cache/paper_state.phantom_audit.json
  - Bot + brain restarted with patched code (PID 13924 bot, PID 5932 brain)

STATE NOW:
  - 1 kotak_bot paper process (NSSM-owned, no duplicates)
  - cash Rs.1,00,000, 0 positions
  - 5% cost cap ACTUALLY ENFORCED
  - Brain using pre-open guard, no more pre-09:15 OPEN writes
  - Bot using order fix (no UnboundLocalError on Order)
  - Bot using both-key cap read
  - All decisions scrubbed (no 'already long' lies)
  - Production audit: 8/8 checks PASSING

COMMITTED + PUSHED:
  8bde613 (main hardening) + 5b0149c (audit script) on master
  github.com/SaiNihal2622/kotak-neo-trading-bot

NEXT: The 14:30 force-square backstop is intact. Brain continues calling
LLM every few minutes. If it issues a new OPEN, the bot will now size
correctly (1 lot = 75 shares NIFTY, not 5625)."""
r = a.send(msg, parse_mode='HTML')
print('sent' if r else 'failed')
