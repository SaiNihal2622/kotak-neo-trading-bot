"""Send the honest status update about today's reset attempt."""
import sys
from pathlib import Path

ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
sys.path.insert(0, str(ROOT / "scripts"))

import os
cred = ROOT / "config" / "credentials.env"
for line in cred.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        if k.strip() not in os.environ:
            os.environ[k.strip()] = v.strip().strip('"').strip("'")

msg = """[Mavis 13:30] Today (Sep 8) — honest update on reset attempt

THE PROBLEM YOU CAUGHT:
Cash Rs.109,068.70 + Realized Rs.16,619.70 was yesterday's poison.
The pre_market reset at 08:25 wrote the clean file (cash=100k, realized=0)
but the running bot's _save_state overwrote it on the next tick
(bot's in-memory state from 12:53 startup had the old values).

WHAT I TRIED:
1. Manual file rewrite from user-context — overwritten by bot within seconds
2. Force-action RESET_PAPER_STATE — bot's exit handler (broker.disconnect)
   also saves the in-memory state, overwriting our clean write
3. Fix to use os._exit(0) — committed (47f623b) but couldn't deploy because
   NSSM restart isn't killing the old bot (pid 18464 still alive 35+ min)
4. Force-action RUN_COMMAND nssm restart — bot processes consume it but
   the nssm exit code is 1 (Access denied) for the new restart

CURRENT STATE:
- Bot alive (pid 18464, NSSM-managed, 35 min uptime)
- Cash: Rs.109,068.70 | Realized: Rs.16,619.70 (yesterday's poison)
- 2 NIFTY spread legs open in broker (orphan in bot's order_mgr)
- 13:30 IST: orphan-auto-close will fire (after my time-gate fix)
  with REAL prices, not Rs.1.00 — the spread will be force-squared
- 14:30 IST: force-square at close

HONEST ASSESSMENT:
The +Rs.16,619.7 can't be un-corrupted without restarting the bot AND
preventing the new bot from saving its in-memory state. I shipped the
os._exit fix (commit 47f623b) but NSSM is failing to restart the bot
through the user-context. The bot is on OLD code.

PROPER FIX (for tomorrow's pre_market):
The pre_market_reset_paper_state.py already runs at 08:25 via NSSM task.
If the bot is running with in-memory state, the same race will occur.
Need to also restart the bot during the pre_market reset, but in a way
that the new bot's _save_state doesn't overwrite the clean state.
Solution: paper_client.py's _save_state checks for a "skip_save" flag
in data_cache/_reset_in_progress.json and skips saving if it exists.
The reset script creates the flag, writes clean state, removes the flag,
then restarts the bot. New bot reads clean state and saves normally.

I will implement this tonight and have it ready for tomorrow.

NEXT STEPS (your call):
1. WAIT — let 14:30 force-square happen with REAL prices (clean
   accounting from then on, the +16,619 becomes a paper-trading rounding
   that you can choose to ignore going forward)
2. MANUAL — close the 2 NIFTY spread legs at the broker yourself
3. AGGRESSIVE — I can take the bot down via the supervisor scheduled
   task (SYSTEM context, has admin) and restart it cleanly
4. WAIT_FOR_TOMORROW — let the new pre_market reset do it at 08:25
   (with the skip-save flag fix I'll ship tonight)

Reply with 1/2/3/4 and I'll execute."""

print(msg)
print("---")
from telegram_alerter import get_alerter
a = get_alerter()
if a and a.enabled:
    if a.send(msg):
        print("Sent to Telegram")
    else:
        print("Telegram send failed")
