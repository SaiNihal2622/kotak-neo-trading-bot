"""Check by_day after dedup."""
import json
sp = json.load(open("data_cache/performance/strategy_performance.json"))
bd = sp.get("by_day", {})
print("by_day:")
for d in sorted(bd.keys()):
    print(f"  {d}: Rs.{bd[d].get('pnl', 0):+,.2f}")
total = sum(b.get("pnl", 0) for b in bd.values())
print(f"Total: Rs.{total:+,.2f}")
print(f"paper_state.realized_pnl: Rs.{json.load(open('data_cache/paper_state.json'))['realized_pnl']:.2f}")
recon = sp.get("reconciliation", {})
print(f"dedup_skipped: {recon.get('duplicate_order_ids_skipped', 0)}")
