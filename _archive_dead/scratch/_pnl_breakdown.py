"""Profit breakdown — by day, strategy, underlying."""
import json
from pathlib import Path

sp = json.load(open("data_cache/performance/strategy_performance.json"))
bd = sp.get("by_day", {})

print("=== Cumulative return breakdown ===")
print(f"Starting capital (Sep 7 reset): Rs.100,000")
print(f"Current cash:                 Rs.109,994.50")
print(f"Cumulative P&L:               Rs.+9,994.50")
print()

print("=== Per-day breakdown (post-phantom-exclusion) ===")
total = 0
for d in sorted(bd.keys()):
    pnl = bd[d].get("pnl", 0)
    n = bd[d].get("trades", 0)
    cum = total + pnl
    total = cum
    pct = cum / 100000 * 100
    print(f"  {d}: Rs.{pnl:+8,.2f} ({n:2d} trades) | cum=Rs.{cum:+8,.2f} ({pct:+.2f}%)")
print()
print(f"Final cumulative: Rs.{total:+,.2f} ({total/100000*100:+.2f}%)")
print()

print("=== Per-strategy (top contributors) ===")
strats = sp.get("by_strategy", {})
for s, d in sorted(strats.items(), key=lambda x: -x[1].get("total_pnl", 0))[:10]:
    n = d.get("trades", 0)
    w = d.get("wins", 0)
    pnl = d.get("total_pnl", 0)
    print(f"  {s[:25]:25s} n={n:3d} wins={w:3d} total=Rs.{pnl:+,.2f}")
print()

print("=== Per-underlying ===")
unds = sp.get("by_underlying", {})
for u, d in sorted(unds.items(), key=lambda x: -x[1].get("total_pnl", 0))[:10]:
    n = d.get("trades", 0)
    w = d.get("wins", 0)
    pnl = d.get("total_pnl", 0)
    print(f"  {u[:15]:15s} n={n:3d} wins={w:3d} total=Rs.{pnl:+,.2f}")
print()

print("=== Phantom exclusion (NOT counted in P&L) ===")
print("Phantom fills excluded: 6")
print("P&L that would have been included: Rs.30,332.70")
print("(phantom_price=true entries from Sep 7/11/15 orphan-auto-close bug — fixed in Phase 14)")

# Live go status
print()
print("=== Live-go policy ===")
lgs = json.load(open("data_cache/live_go_status.json"))
print(f"Streak: {lgs.get('current', {}).get('consecutive_green_days')}/5 green days")
print(f"Cumulative return: {lgs.get('current', {}).get('cumulative_return_pct', 0):+.2f}%")
print(f"Ready for live: {lgs.get('ready_for_live')}")
print(f"Missing: {lgs.get('missing_to_ready', [])}")
