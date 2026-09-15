"""Today's P&L summary - one-shot diagnostic."""
import json
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
d = json.load(open(ROOT / "data_cache" / "paper_state.json"))
print("=" * 70)
print("CASH & REALIZED PnL")
print("=" * 70)
print(f"  Cash:          Rs.{d['cash']:>15,.2f}")
print(f"  Realized PnL:  Rs.{d['realized_pnl']:>15,.2f}")
print(f"  Open positions: {len(d['positions'])}")
print()
print("=" * 70)
print("TODAY'S ORDERS (2026-09-08)")
print("=" * 70)
today_orders = [o for oid, o in d["orders"].items() if "2026-09-08" in str(o.get("placed_at", ""))]
print(f"Total today: {len(today_orders)}")
print()
# Group by tag
for o in sorted(today_orders, key=lambda x: x.get("placed_at", "")):
    side = o.get("side", "?")
    qty = o.get("qty", "?")
    sym = o.get("symbol", "?")
    px = o.get("avg_fill_price", 0)
    status = o.get("status", "?")
    tag = o.get("tag", "?")[:30]
    placed = o.get("placed_at", "?")[:19]
    print(f"  {placed}  {side:5} {qty:>3}  {sym:30} @ Rs.{px:>8,.2f}  status={status:10}  tag={tag}")

print()
print("=" * 70)
print("TRADE JOURNAL (FILL events only)")
print("=" * 70)
journal = []
with open(ROOT / "data_cache" / "trade_journal.jsonl") as f:
    for line in f:
        if not line.strip():
            continue
        try:
            e = json.loads(line)
            if e.get("event") == "FILL":
                journal.append(e)
        except Exception:
            pass

# Filter to today
today_fills = [e for e in journal if "2026-09-08" in str(e.get("ts", ""))]
print(f"Total FILL events today: {len(today_fills)}")
total_realized = 0
for e in sorted(today_fills, key=lambda x: x.get("ts", "")):
    side = e.get("side", "?")
    qty = e.get("qty", "?")
    sym = e.get("symbol", "?")
    px = e.get("avg_fill_price", 0)
    realized = e.get("realized_delta", 0)
    tag = e.get("tag", "?")[:30]
    ts = e.get("ts", "?")[:19]
    total_realized += realized
    print(f"  {ts}  {side:5} {qty:>3}  {sym:30} @ Rs.{px:>8,.2f}  delta=Rs.{realized:>+10,.2f}  tag={tag}")
print()
print(f"SUM OF realized_delta TODAY: Rs.{total_realized:+,.2f}")
print(f"paper_state.json realized_pnl: Rs.{d['realized_pnl']:+,.2f}")
print()
print("=" * 70)
print("DAILY.JSON (yesterday's reconstruction)")
print("=" * 70)
try:
    perf = json.load(open(ROOT / "data_cache" / "performance" / "daily.json"))
    for k in ("date", "trades", "closed", "wins", "losses", "win_rate",
              "realized_pnl", "suspect_fill_count", "suspect_pnl",
              "honest_pnl_estimate", "data_quality"):
        print(f"  {k:30} = {perf.get(k, '?')}")
except Exception as e:
    print(f"  (no daily.json: {e})")
