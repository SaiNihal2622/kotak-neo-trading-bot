"""Send the round-3 summary (the "do both and more" follow-up) to Telegram."""
import sys
from pathlib import Path

ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
sys.path.insert(0, str(ROOT / "scripts"))

# Load env
import os
cred = ROOT / "config" / "credentials.env"
for line in cred.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        if k.strip() not in os.environ:
            os.environ[k.strip()] = v.strip().strip('"').strip("'")

msg = """[Mavis 23:25] Round 3 SHIPPED — both fixes + more

1. ORPHAN-AUTO-CLOSE TIME-GATE (commit eb494ce)
   Was: closed any orphan position on every scan if OTM + small.
   Now: only fires AFTER 13:30 IST (no-new-trades time). Before 13:30,
   brain-driven positions get a fair hold window for theta capture.
   Today's BNF (closed at 12:04) and NIFTY (closed at 12:42) would
   have been left alone.

2. PAPER STATE RESET (commit eb494ce)
   Tomorrow at 08:25 IST (pre-market), paper_state.json will reset to
   a clean Rs.100,000 baseline. Old state backed up to
   paper_state_pre_reset_<ts>.json. RESET entry appended to journal.
   Trigger: data_cache/_reset_marker.json (already created).

3. SUSPECT PRICE FLAG (commit eb494ce)
   Any fill with avg_fill_price=1.00 + no expected price + ORPHAN tag
   is now tagged suspect_price=true. Today's daily.json has:
     - suspect_fill_count: 3
     - suspect_pnl: Rs.18,586 (the artificial component)
     - honest_pnl_estimate: Rs.-1,702 (real P&L)
     - data_quality: 'partial_fake'

4. SELF-HEAL RECIPE: inline_journal_missing (commit eb494ce)
   New recipe. Detects if bot's stderr log lacks the 'inline trade_journal
   callback registered' message in last 10 min. Fix: nssm restart.

5. TESTS: 392 pass (was 382, +10)
   - 9 new time-gate tests
   - Extended reconstruction tests with suspect_price assertions

BOT STATUS: PID 3388, new code deployed, uptime 30s, healthy
TOMORROW: clean Rs.100,000 baseline at 08:25 IST, honest P&L tracking."""

print(msg)
print("---")
from telegram_alerter import get_alerter
a = get_alerter()
if a and a.enabled:
    if a.send(msg):
        print("Sent to Telegram")
    else:
        print("Telegram send failed")
else:
    print("Telegram alerter not enabled — message NOT sent")
