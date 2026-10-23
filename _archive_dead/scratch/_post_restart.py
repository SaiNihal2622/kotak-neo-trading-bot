"""Decisions since restart."""
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))
now = datetime.now(IST)
restart = now.replace(hour=14, minute=10, second=0)

lines = Path("data_cache/quant_service_decisions.jsonl").read_text(encoding="utf-8").strip().split("\n")
post = []
for ln in lines:
    try:
        r = json.loads(ln)
        ts_str = r.get("ts", "")
        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        ts_ist = ts.astimezone(IST)
        if ts_ist > restart:
            post.append(r)
    except Exception:
        pass

print(f"Decisions since 14:10 IST restart: {len(post)}")
holds = sum(1 for r in post if r.get("decision", {}).get("type") == "HOLD")
opens = sum(1 for r in post if r.get("decision", {}).get("type") == "OPEN")
print(f"  HOLD: {holds}, OPEN: {opens}")

print("Last 5 decisions:")
for r in post[-5:]:
    d = r.get("decision", r)
    rat = str(d.get("rationale", ""))[:120]
    print(f"  {r.get('ts', '?')[:19]} {d.get('type', '?')} | {rat}")
