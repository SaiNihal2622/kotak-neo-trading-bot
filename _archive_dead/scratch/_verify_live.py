"""Verify: is +57,381 real? Why is paper_state only +9,994.50?"""
import json
from collections import Counter
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))
today = datetime.now(IST).strftime("%Y-%m-%d")

# 1. Read paper_state
state = json.load(open("data_cache/paper_state.json"))
cash = state.get("cash", 0)
realized_pnl = state.get("realized_pnl", 0)
positions = state.get("positions", {})
orders = state.get("orders", {})

print("=" * 70)
print("PAPER STATE (live, current session)")
print("=" * 70)
print(f"  Cash:            Rs.{cash:,.2f}")
print(f"  Realized P&L:    Rs.{realized_pnl:,.2f}")
print(f"  Starting cap:    Rs.{cash - realized_pnl:,.2f}")
print(f"  Open positions:  {len(positions)}")
print()

# 2. Today's fills (live journal)
fills_today = []
fills_all = []
phantom_count = 0
phantom_pnl = 0
with open("data_cache/trade_journal.jsonl", encoding="utf-8") as f:
    for line in f:
        try:
            r = json.loads(line)
            if r.get("event") != "FILL":
                continue
            fills_all.append(r)
            if r.get("phantom_price"):
                phantom_count += 1
                phantom_pnl += (r.get("realized_delta", 0) or 0)
            if today in str(r.get("ts", ""))[:10]:
                fills_today.append(r)
        except Exception:
            pass

print("=" * 70)
print("JOURNAL (all-time fills)")
print("=" * 70)
print(f"  Total FILL events:           {len(fills_all)}")
print(f"  Phantom fills (excluded):    {phantom_count}")
print(f"  Phantom P&L excluded:        Rs.{phantom_pnl:,.2f}")
print()

# Sum realized_delta vs realized_pnl across all non-phantom fills
realized_delta_sum = 0
for f in fills_all:
    if f.get("phantom_price"):
        continue
    realized_delta_sum += (f.get("realized_delta", 0) or 0)
print(f"  Sum of realized_delta (non-phantom): Rs.{realized_delta_sum:,.2f}")
print()

# 3. Check the difference
sp = json.load(open("data_cache/performance/strategy_performance.json"))
bd = sp.get("by_day", {})
strat_perf_total = sum(d.get("pnl", 0) for d in bd.values())
print("=" * 70)
print("WHY TWO DIFFERENT NUMBERS?")
print("=" * 70)
print(f"  strategy_performance.by_day total:  Rs.{strat_perf_total:,.2f}")
print(f"  paper_state.realized_pnl:           Rs.{realized_pnl:,.2f}")
print(f"  Diff:                              Rs.{strat_perf_total - realized_pnl:,.2f}")
print()

# Where did the diff come from?
print("=" * 70)
print("PER-DAY BREAKDOWN (strategy_performance.by_day)")
print("=" * 70)
for d in sorted(bd.keys()):
    pnl = bd[d].get("pnl", 0)
    n = bd[d].get("trades", 0)
    print(f"  {d}: Rs.{pnl:+10,.2f} ({n} trades)")
print()

# When was paper_state last reset?
# Check the date of the latest "old" Sep 15 trade in journal that doesn't reflect in state
sep15_orders_in_state = 0
for oid, o in orders.items():
    pa = o.get("placed_at", "")
    if "2026-09-15" in pa:
        sep15_orders_in_state += 1
print(f"  Sep 15 orders in paper_state.orders: {sep15_orders_in_state}")

# Find earliest trade in journal
fills_sorted = sorted(fills_all, key=lambda x: str(x.get("ts", "")))
if fills_sorted:
    print(f"  Earliest fill: {fills_sorted[0].get('ts', '?')[:19]} | {fills_sorted[0].get('symbol')}")
    print(f"  Latest fill:   {fills_sorted[-1].get('ts', '?')[:19]} | {fills_sorted[-1].get('symbol')}")
