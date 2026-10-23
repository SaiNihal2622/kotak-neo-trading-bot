"""One-time restore from Sep 17 EOD backup.
The paper_state.json was corrupted on shutdown. This script:
1. Reads data_cache/backups/20260917_230001/paper_state.json
2. Fixes the realized_pnl bookkeeping (was 3,778.50 in backup; should be 9,994.50
   to match cash delta — the 0DTE iron condor settlement was captured in cash
   but missed in realized_pnl)
3. Clears the 4 expired 0DTE iron condor positions (Sep 17 EXPIRY — already
   settled into cash)
4. Writes the corrected paper_state.json
5. Backs up the corrupt/reset state first for traceability
"""
import json
import shutil
from pathlib import Path
from datetime import datetime

ROOT = Path(".").resolve()
PS = ROOT / "data_cache" / "paper_state.json"
BACKUP = ROOT / "data_cache" / "backups" / "20260917_230001" / "paper_state.json"

# Safety: back up the current (broken) state first
ps_lwt = PS.stat().st_mtime
broken_path = ROOT / "data_cache" / f"paper_state_pre_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
shutil.copy2(PS, broken_path)
print(f"[restore] backed up current state to {broken_path.name}")

# Read the Sep 17 EOD backup
src = json.loads(BACKUP.read_text(encoding="utf-8"))
print(f"[restore] backup cash = Rs.{src['cash']:,.2f}")
print(f"[restore] backup realized_pnl = Rs.{src['realized_pnl']:,.2f}")
print(f"[restore] backup positions = {len(src.get('positions', {}))} (will be cleared — 0DTE Sep 17 EXPIRY)")

# Compute the correct realized_pnl from cash delta
starting_capital = 100000.0
computed_realized = src["cash"] - starting_capital
print(f"[restore] computed realized_pnl = cash - starting_capital = Rs.{computed_realized:,.2f}")

# Build the restored state
restored = {
    "cash": src["cash"],  # Rs.109,994.50 — truth from backup
    "realized_pnl": round(computed_realized, 2),  # Rs.9,994.50 — match cash delta
    "orders": {},  # cleared — orders are stale; bot rebuilds from journal
    "positions": {},  # cleared — 4 iron condor legs are Sep 17 0DTE EXPIRED,
                      # already settled into cash
    "_restored_at": datetime.now().isoformat(),
    "_restored_from": str(BACKUP.relative_to(ROOT)),
    "_restored_reason": (
        "Sep 19 21:06 paper_state corruption during shutdown; bot fell back to "
        "fresh Rs.100,000 starting capital. Restored cash from Sep 17 EOD backup "
        "(Rs.109,994.50) and computed realized_pnl as cash delta. The 4 iron "
        "condor legs from Sep 17 are EXPIRED 0DTE and already settled into cash."
    ),
}

# Write the restored paper_state.json
PS.write_text(json.dumps(restored, indent=2), encoding="utf-8")
print()
print(f"[restore] wrote paper_state.json:")
print(f"  cash          = Rs.{restored['cash']:,.2f}")
print(f"  realized_pnl  = Rs.{restored['realized_pnl']:+,.2f}")
print(f"  orders        = {len(restored['orders'])}")
print(f"  positions     = {len(restored['positions'])}")
print()
print(f"[restore] NEXT STEP: restart the bot so it loads the new state:")
print(f"  nssm restart KotakBotPaper")
print(f"  python -m scripts.live_go_tracker.py  # re-evaluate streak")