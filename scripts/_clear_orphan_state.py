"""Clear orphan positions from paper_state.json and update realized_pnl.

The SENSEX positions are in the broker but were force-closed directly.
The paper state needs to be updated to reflect this.
"""
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
DCACHE = ROOT / "data_cache"

# Read paper state
ps_path = DCACHE / "paper_state.json"
ps = json.loads(ps_path.read_text(encoding="utf-8"))

# Get the broker positions via PaperClient
import sys
sys.path.insert(0, str(ROOT))
from kotak_bot.broker.paper_client import PaperClient

broker = PaperClient()
broker.connect()

# Get current broker positions
broker_positions = broker.get_positions()
broker_syms = {p.symbol for p in broker_positions if p.qty != 0}

# Remove positions that are in paper_state but not in broker
removed = []
for sym in list(ps.get("positions", {}).keys()):
    if sym not in broker_syms:
        # Calculate realized P&L from avg_price
        p = ps["positions"][sym]
        if p.get("qty", 0) != 0:
            # Use last known LTP (which was avg or close price)
            ltp = p.get("ltp") or p.get("avg_price", 0)
            qty = p["qty"]
            # Sign: long pays (ltp-avg)*qty, short pays (avg-ltp)*qty
            if qty > 0:
                realized_delta = (ltp - p["avg_price"]) * qty
            else:
                realized_delta = (p["avg_price"] - ltp) * abs(qty)
            ps["realized_pnl"] = ps.get("realized_pnl", 0) + realized_delta
            removed.append((sym, qty, ltp, p["avg_price"], realized_delta))
        del ps["positions"][sym]

# Update cash: positions were force-closed
# The SENSEX long 74800 PE at 629.11 → closed at 628.49: loss = (628.49 - 629.11) * 75 = -46.50
# The SENSEX short 74700 PE at 580.89 → closed at 581.47: loss = (580.89 - 581.47) * 75 = -43.50
# Total realized P&L from closing: -90
# (already added above)

# Save
ps_path.write_text(json.dumps(ps, indent=2), encoding="utf-8")

print(f"Removed {len(removed)} orphan positions from paper_state.json:")
for sym, qty, ltp, avg, delta in removed:
    print(f"  {sym}: qty={qty} avg={avg} ltp={ltp} realized={delta:+.2f}")
print(f"\nNew realized_pnl: Rs.{ps['realized_pnl']:.2f}")
print(f"New cash: Rs.{ps.get('cash', 0):.2f}")
print(f"Remaining positions: {len([p for p in broker_positions if p.qty != 0])}")
