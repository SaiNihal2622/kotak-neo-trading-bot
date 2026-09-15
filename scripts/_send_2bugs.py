#!/usr/bin/env python
"""Send the 2-bug fix report to Telegram."""
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
msg = """[Mavis 11:10] SECOND BUG FIXED — bot was rejecting all OPENs due to Python scoping error

BUG (10:31 OPEN lost)
  Brain issued NIFTY long_put (BUY 24000 PE, target 120, stop 55) at 10:31.
  Bot tried to place, crashed with:
    UnboundLocalError: cannot access local variable 'Order' where it is not associated with a value

ROOT CAUSE
  At line 664 inside run_paper(), an earlier block did
    from kotak_bot.broker.base import Order, OrderSide, OrderType, ProductType
  Python's compiler marks any 'from X import Y' inside a function as making Y a
  local for the entire function. So the later Order(...) at line ~1071 saw
  Order as unbound.

SAME class of bug as the 2026-08-27 'from pathlib import Path' shadowing
that orphaned 8 BNF condor legs. This is the SECOND time the from-import-
inside-function shadowing bit us in this file.

FIX
  Top-level import at line 26 already provides Order/OrderSide/etc. Removed
  the redundant inner import. Added a comment explaining the trap so the
  next refactor doesn't reintroduce it.

FIX DEPLOYED
  Bot restarted (PID 7204, uptime 2.5min, alive, thread OK). Brain restarted
  with full pre-open guard. Both bugs now live in production.

RECOVERED
  NIFTY fell from ~24,000 to 23,836 (-165 pts) since the 10:31 signal. The
  long_put at strike 24000 would have been +Rs.100-150 winner. Cannot
  recover — system is forward-only.

COMMITTED + PUSHED
  5dc58ef on master, 4 insertions, 1 deletion. Repo: github.com/SaiNihal2622/kotak-neo-trading-bot

NEXT
  Brain continues calling LLM. With VIX 11.9 (calm), NIFTY at session lows,
  may issue more OPENs. Bot will now execute them correctly."""
r = a.send(msg, parse_mode='HTML')
print('sent' if r else 'failed')
