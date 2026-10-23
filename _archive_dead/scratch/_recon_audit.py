"""Find where the Rs.47,386.50 discrepancy comes from."""
import json
from collections import defaultdict
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))

# Walk every fill, group by status (FILL, RECON, closed_eod, etc.)
# and check realized_delta vs realized_pnl fields
fills = []
with open("data_cache/trade_journal.jsonl", encoding="utf-8") as f:
    for line in f:
        try:
            r = json.loads(line)
            if r.get("event") == "FILL":
                fills.append(r)
        except Exception:
            pass

print(f"Total fills: {len(fills)}")
print()

# Bucket by status field
by_status = defaultdict(list)
for f in fills:
    status = f.get("status", "complete")
    by_status[status].append(f)

for status, flist in by_status.items():
    total = sum(f.get("realized_delta", 0) or 0 for f in flist)
    pnl_field = sum(f.get("realized_pnl", 0) or 0 for f in flist)
    print(f"status='{status}': {len(flist)} fills | sum realized_delta={total:+,.2f} | sum realized_pnl={pnl_field:+,.2f}")

# Now look at RECON entries
print()
print("=== RECON entries (reconstructed) ===")
recon = [f for f in fills if "RECON" in (f.get("trade_id", "") or "")]
print(f"Count: {len(recon)}")
total_recon_pnl = sum(f.get("realized_pnl", 0) or 0 for f in recon)
print(f"Sum realized_pnl: Rs.{total_recon_pnl:+,.2f}")
for r in recon[:10]:
    sym = r.get("symbol", "")
    pnl = r.get("realized_pnl", 0) or 0
    print(f"  {r.get('trade_id', '?')[:50]} | {sym} | realized_pnl=Rs.{pnl:+,.2f}")

# EOD entries
print()
print("=== EOD (closed_eod) entries ===")
eod = [f for f in fills if f.get("status") == "closed_eod"]
print(f"Count: {len(eod)}")
total_eod_pnl = sum(f.get("realized_pnl", 0) or 0 for f in eod)
print(f"Sum realized_pnl: Rs.{total_eod_pnl:+,.2f}")

# Inline fills (the actual paper fills)
print()
print("=== Inline fills (event=FILL, status=complete) ===")
inline = [f for f in fills if f.get("status") == "complete"]
print(f"Count: {len(inline)}")
total_inline = sum(f.get("realized_delta", 0) or 0 for f in inline)
print(f"Sum realized_delta: Rs.{total_inline:+,.2f}")
# What's their actual realized_delta sum vs paper_state's realized_pnl?
print(f"Paper state realized_pnl: Rs.{json.load(open('data_cache/paper_state.json'))['realized_pnl']:+,.2f}")
print(f"Match: {'YES' if abs(total_inline - 9994.50) < 1 else 'NO'}")

# Reconciliation
print()
print("=== RECONCILIATION ===")
print(f"Paper state.cash:                Rs.{json.load(open('data_cache/paper_state.json'))['cash']:,.2f}")
print(f"Paper state.realized_pnl:        Rs.{json.load(open('data_cache/paper_state.json'))['realized_pnl']:,.2f}")
print(f"Sum of inline realized_delta:    Rs.{total_inline:+,.2f}")
print(f"Sum of RECON realized_pnl:        Rs.{total_recon_pnl:+,.2f}")
print(f"Sum of EOD realized_pnl:          Rs.{total_eod_pnl:+,.2f}")
print()
print(f"by_day sum (what strategy_perf reports): Rs.57,381.00")
print(f"Inline fills only:                        Rs.{total_inline:+,.2f}")
print(f"DIFF (by_day - inline): Rs.{57381 - total_inline:+,.2f} ← comes from RECON + EOD aggregations")
