"""Check rejections since bot restart."""
import json
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))
now_ist = datetime.now(IST)
restart_ist = now_ist.replace(hour=11, minute=30, second=35)
print(f"Bot restarted at: {restart_ist.strftime('%H:%M:%S')} IST")
print(f"Current time: {now_ist.strftime('%H:%M:%S')} IST")
print(f"Since restart: {(now_ist - restart_ist).total_seconds():.0f}s")
print()

# Rejections since restart
rejs_post = []
rejs_pre = []
with open("data_cache/order_rejections.jsonl", encoding="utf-8") as f:
    for line in f:
        try:
            r = json.loads(line)
            ts_str = r.get("ts", "")
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                ts_ist = ts.astimezone(IST)
                if ts_ist > restart_ist:
                    rejs_post.append(r)
                else:
                    rejs_pre.append(r)
            except Exception:
                pass
        except Exception:
            pass

print(f"Rejections since restart: {len(rejs_post)}")
print(f"Rejections pre-restart (still in log): {len(rejs_pre)}")
if rejs_post:
    print("Last 5 post-restart rejections:")
    for r in rejs_post[-5:]:
        print(f"  {r.get('ts', '?')[:19]} | reason={str(r.get('reason', ''))[:80]}")

# Open decisions since restart
opens_post = []
all_decisions = []
with open("data_cache/quant_service_decisions.jsonl", encoding="utf-8") as f:
    for line in f:
        try:
            r = json.loads(line)
            d = r.get("decision", {})
            ts_str = r.get("ts", "")
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                ts_ist = ts.astimezone(IST)
                if ts_ist > restart_ist:
                    if d.get("type") == "OPEN":
                        opens_post.append(r)
            except Exception:
                pass
        except Exception:
            pass
print(f"\nOPEN decisions since restart: {len(opens_post)}")
for r in opens_post[-3:]:
    d = r.get("decision", {})
    print(f"  {r.get('ts', '?')[:19]} {d.get('strategy', '?')[:30]} | rationale: {str(d.get('rationale', ''))[:100]}")
