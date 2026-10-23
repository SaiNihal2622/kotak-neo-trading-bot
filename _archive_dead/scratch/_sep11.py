"""Verify Sep 11 fills."""
import json

fills = []
with open("data_cache/trade_journal.jsonl", encoding="utf-8") as f:
    for line in f:
        try:
            r = json.loads(line)
            if r.get("event") != "FILL":
                continue
            ts = str(r.get("ts", ""))[:10]
            if ts == "2026-09-11":
                fills.append(r)
        except Exception:
            pass

total = 0
for f in fills:
    delta = f.get("realized_delta", 0) or 0
    total += delta
    sym = f.get("symbol", "")
    side = f.get("side", "")
    qty = f.get("qty", 0)
    px = f.get("avg_fill_price", 0)
    tag = f.get("tag", "")
    ts_str = f.get("ts", "?")[:19]
    print(f"  {ts_str} | {side} {sym} x{qty} @ {px} | delta=Rs.{delta:+.2f} | tag={tag}")
print(f"Sum: Rs.{total:+.2f}")
