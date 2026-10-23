"""Identify strikes with phantom-fill history."""
import json
from collections import Counter
from pathlib import Path

qp = Path("data_cache/trade_journal.jsonl")
phantom_strikes = Counter()
total = 0
phantom_count = 0
with qp.open(encoding="utf-8") as f:
    for line in f:
        try:
            r = json.loads(line)
            if not r.get("phantom_price"):
                continue
            phantom_count += 1
            sym = r.get("symbol", "")
            if sym:
                phantom_strikes[sym] += 1
            total += 1
        except Exception:
            pass

print(f"Total phantom fills in journal: {phantom_count}")
print(f"Unique phantom strikes:")
for sym, n in phantom_strikes.most_common():
    print(f"  {sym}: {n}x")
