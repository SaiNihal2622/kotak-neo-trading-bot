"""Find TRUE duplicates: same order_id appearing twice."""
import json
from collections import Counter
from pathlib import Path

qp = Path("data_cache/trade_journal.jsonl")
order_ids = []
fills = []
with qp.open(encoding="utf-8") as f:
    for line in f:
        try:
            r = json.loads(line)
            if r.get("event") != "FILL":
                continue
            oid = r.get("order_id")
            if oid:
                order_ids.append(oid)
                fills.append(r)
        except Exception:
            pass

cnt = Counter(order_ids)
true_dupes = {k: v for k, v in cnt.items() if v > 1}
print(f"Total FILL entries: {len(fills)}")
print(f"Unique order_ids: {len(set(order_ids))}")
print(f"True duplicates (same order_id twice): {len(true_dupes)}")
if true_dupes:
    print("\nFirst 3 dupes:")
    for oid, n in list(true_dupes.items())[:3]:
        entries = [r for r in fills if r.get("order_id") == oid]
        print(f"\n  {oid} appears {n}x:")
        for e in entries:
            print(f"    {e.get('ts', '?')[:19]} | {e.get('symbol')} {e.get('side')} x{e.get('qty')} @ {e.get('avg_fill_price')}")
