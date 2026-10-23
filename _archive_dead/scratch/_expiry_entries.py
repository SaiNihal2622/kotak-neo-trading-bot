"""Find all EXPIRY entries."""
import json
exp = []
with open("data_cache/trade_journal.jsonl", encoding="utf-8") as f:
    for line in f:
        try:
            r = json.loads(line)
            if r.get("trade_id", "").startswith("EXPIRY-"):
                exp.append(r)
        except Exception:
            pass
print(f"Total EXPIRY entries: {len(exp)}")
for e in exp:
    print(f"  {e.get('trade_id')} | {e.get('symbol')} | delta={e.get('realized_delta')}")
