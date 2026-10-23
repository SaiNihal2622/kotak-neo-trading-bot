"""Today's orders + rejections detail."""
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30))
now = datetime.now(IST)
today = now.strftime("%Y-%m-%d")

# Today's rejections
rejs = []
with open("data_cache/order_rejections.jsonl", encoding="utf-8") as f:
    for line in f:
        try:
            r = json.loads(line)
            ts = r.get("ts", "")
            if today not in ts[:10]:
                continue
            ts_obj = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            ts_ist = ts_obj.astimezone(IST)
            if ts_ist.date() == now.date():
                rejs.append(r)
        except Exception:
            pass
print(f"Today rejections: {len(rejs)}")
for r in rejs[-5:]:
    sym = r.get("symbol", "?")[:30]
    reason = str(r.get("reason", ""))[:80]
    print(f"  {r.get('ts', '?')[:19]} | {sym} | {reason}")

print()
# Today's placed orders (paper_state.json orders)
state = json.load(open("data_cache/paper_state.json"))
orders = state.get("orders", {})
placed_today = []
for oid, o in orders.items():
    fa = o.get("filled_at", "") or ""
    pa = o.get("placed_at", "") or ""
    if today in (fa[:10] if fa else "") or today in (pa[:10] if pa else ""):
        placed_today.append((oid, o))
print(f"Orders placed or filled today: {len(placed_today)}")
for oid, o in placed_today[-8:]:
    side = o.get("side")
    sym = o.get("symbol", "")[:30]
    qty = o.get("qty")
    st = o.get("status")
    pa = str(o.get("placed_at", "?"))[:19]
    fa = str(o.get("filled_at", "?") or "NEVER")[:19]
    px = o.get("avg_fill_price", 0)
    rej = o.get("rejection_reason", "")[:50]
    print(f"  {oid[:18]} | {side} {sym} x{qty} | st={st} px={px} | placed={pa} | filled={fa} | rej={rej}")

print()
# Today's bot stderr log lines about orders
print("=== Recent bot log (last 30 order/place/fill/reject lines) ===")
import subprocess
result = subprocess.run(
    ["powershell", "-NoProfile", "-Command", "Get-Content 'Logs\\bot_stderr.log' -Tail 200 | Select-String -Pattern 'PLACE|FILL|TIMEOUT|REJECT|FORCE-SQUARE|EXPIRY' | Select-Object -Last 20"],
    capture_output=True, text=True, cwd="."
)
print(result.stdout[:3000])
