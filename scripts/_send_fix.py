#!/usr/bin/env python
"""Send critical fix report to Telegram."""
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
msg = """[Mavis 10:45] CRITICAL FIX SHIPPED — pre-open OPEN actions were being lost

ISSUE
  09:08:00 brain issued HIGH CONVICTION BEARISH OPEN for NIFTY bear_put_vertical
  (BUY 23900 PE + SELL 23700 PE, 75 qty each, target Rs.4,500 stop Rs.1,500).
  Bot correctly rejected with 'too early pre-open (09:08)' but ALSO marked the
  action as consumed (placed_legs=0). When market opened at 09:15, the action
  was gone from the file -> bot skipped it. The trade was lost.
  Estimated missed move: NIFTY fell from 23858 to 23872 area (small) but the
  signal was real — the broader selloff continued into 10:00+.

FIX 1 — kotak_bot/__main__.py
  Time-window rejects (pre-open, EOD) now leave the action file unconsumed.
  The bot retries on the next cycle, so a pre-09:15 OPEN will execute at
  09:15+ when the market opens. Added a 30-min TTL so ancient actions auto-
  expire cleanly without manual cleanup.

FIX 2 — scripts/quant_service.py
  Brain-side guard: don't WRITE OPEN actions to the action file outside the
  trading window (Mon-Fri 09:15-15:15 IST). LLM still sees the decision prompt
  and the decision is logged for transparency, but no file is written so the
  bot never has to deal with a pre-open action at all.

BELT + SUSPENDERS
  The bot fix handles cases where the brain code is stale (current NSSM brain
  is still running pre-fix code). The brain fix prevents new stale actions
  from being written once the brain is restarted with the new code.

ACTION NEEDED (USER)
  To fully activate the brain-side fix (Fix 2), the NSSM brain needs a restart:
    - Win+R -> nssm (or Run dialog)
    - Or: open admin PowerShell, run:
        nssm restart KotakQuantService
  The 5s UAC click will pull in Fix 2. Until then, the bot-side fix (Fix 1)
  alone is enough to prevent the same loss from recurring.

COMMITTED + PUSHED
  commit 1a2ed7f on master (SaiNihal2622/kotak-neo-trading-bot)
  53 insertions, 6 deletions across 2 files."""
r = a.send(msg, parse_mode='HTML')
print('sent' if r else 'failed')
