"""Send the 13:50 IST status update to Telegram."""
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

msg = """[Mavis 13:50] Today (Sep 8) status update

BOT: alive, PID 18464, 57 min uptime, on OLD code (NSSM restart from user-context keeps failing)
- 17 crashes today from my force-action attempts (no data loss, NSSM respawns)
- Cash: Rs.109,068.70 | Realized: Rs.16,619.70 (still yesterday's poison)

TODAY'S TRADING:
- 1 NIFTY bear_put spread (09:43): BUY 75 NIFTY 24800 PE @ Rs.1123.57, SELL 75 NIFTY 24700 PE @ Rs.1022.89
- Both opens at REAL prices (no Rs.1.00 bug)
- Inline journal: 2 FILL entries + 1 EOD RECON
- 2 orphan positions in broker (bot's order_mgr doesn't know about them)

BUG I JUST FOUND:
The orphan-auto-close time-gate (commit eb494ce) has a logic bug.
The orphan check is INSIDE the scan block. After 13:30, the scan
SKIPS the whole block ("skip: intraday mode — no_new_trades_after
hit"), so the orphan check NEVER FIRES. Last orphan log was 13:29:51.

REAL SCHEDULE NOW:
- 13:30: orphan-auto-close should have fired (bug: it didn't)
- 14:30: force-square at close (40 min away) — will close the 2
  NIFTY spread legs at REAL prices. Real accounting starts then.
- 15:30: market close

YOUR CALL:
1. FIX BUG + DEPLOY (5 min): move orphan check OUT of the scan
   block so it runs every cycle. Then 14:30 force-square AND the
   13:30 orphan-auto-close both work. Future days are clean.
2. WAIT: let 14:30 force-square close it with real prices. The
   +Rs.16,619 in realized stays contaminated. Tomorrow's pre_market
   reset (with skip-save flag fix) cleans it.
3. RESET NOW: take the bot down via the supervisor scheduled task
   (SYSTEM context, has admin), restart it with clean state.

The +Rs.16,619 is the elephant in the room. The skip-save flag fix
I want to ship tonight would prevent the same race in tomorrow's
pre_market reset. But today's reset can't be done cleanly because
the bot's _save_state runs on every tick and overwrites any file write.

Reply 1/2/3 and I'll execute. Default: 2 (wait for 14:30)."""

print(msg)
print("---")
from telegram_alerter import get_alerter
a = get_alerter()
if a and a.enabled:
    if a.send(msg):
        print("Sent to Telegram")
    else:
        print("Telegram send failed")
