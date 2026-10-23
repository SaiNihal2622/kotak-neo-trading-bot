"""Why all 53 OPEN attempts got rejected today."""
import json
from collections import Counter
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))
today = datetime.now(IST).strftime("%Y-%m-%d")

rejs = []
with open("data_cache/order_rejections.jsonl", encoding="utf-8") as f:
    for line in f:
        try:
            r = json.loads(line)
            if today in str(r.get("ts", ""))[:10]:
                rejs.append(r)
        except Exception:
            pass

print(f"Total today's rejections: {len(rejs)}")
print()
print("Top rejection reasons:")
from collections import Counter
c = Counter(str(r.get("reason", ""))[:60] for r in rejs)
for reason, n in c.most_common(8):
    print(f"  {n:4d}x  {reason}")

# Check strike sanity rejections specifically
sanity = [r for r in rejs if "strike_sanity" in str(r.get("reason", ""))]
print(f"\nStrike-sanity rejections: {len(sanity)} (LLM picked bad strikes)")

# Check fills: did any happen AFTER chain fallback was added?
# Phase 15 was deployed at ~14:10. Anything filled after that?
print("\nFills since 14:10 (post-Phase 15):")
fills = []
with open("data_cache/trade_journal.jsonl", encoding="utf-8") as f:
    for line in f:
        try:
            r = json.loads(line)
            if r.get("event") != "FILL":
                continue
            ts = r.get("ts", "")
            if "2026-09-18T1" in ts[:13] and today in ts[:10]:
                fills.append(r)
        except Exception:
            pass
print(f"  Today's fills: {len(fills)}")
for f in fills:
    print(f"    {f.get('ts', '?')[:19]} {f.get('side')} {f.get('symbol')} @ {f.get('avg_fill_price')} | {f.get('tag', '')}")
