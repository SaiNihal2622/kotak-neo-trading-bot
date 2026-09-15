"""Weekly P&L summary by day."""
import json
from collections import Counter
days = Counter()
fills_by_day = Counter()
with open('data_cache/trade_journal.jsonl') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        ts = d.get('ts', '')[:10]
        pnl = d.get('realized_delta', 0) or 0
        days[ts] += pnl
        fills_by_day[ts] += 1
for d, p in sorted(days.items()):
    print(f"  {d}: Rs.{p:+,.0f}  ({fills_by_day[d]} fills)")
total = sum(days.values())
print(f"\nTotal realized: Rs.{total:+,.0f}")

