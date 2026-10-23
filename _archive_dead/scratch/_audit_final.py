"""What's still suboptimal after Phase 15."""
import json
from collections import Counter
from pathlib import Path

ROOT = Path(".").resolve()
DCACHE = ROOT / "data_cache"

print("=== What's still suboptimal after Phase 15 ===\n")

# 1. Live tick subscription coverage
print("--- Live tick feed coverage ---")
try:
    feed = json.loads((DCACHE / "mavis_realtime_state.json").read_text(encoding="utf-8"))
    if "live_feed" in feed:
        lf = feed["live_feed"]
        subs = lf.get("subscribed", "n/a")
        print(f"  subscribed: {subs}")
except Exception as e:
    print(f"  realtime_state err: {e}")

# 2. Rejection causes
print("\n--- Today's rejection reasons ---")
rejs = []
with open(DCACHE / "order_rejections.jsonl", encoding="utf-8") as f:
    for line in f:
        try:
            rejs.append(json.loads(line))
        except Exception:
            pass
from datetime import datetime, timezone, timedelta
IST = timezone(timedelta(hours=5, minutes=30))
today = datetime.now(IST).strftime("%Y-%m-%d")
today_rejs = [r for r in rejs if today in str(r.get("ts", ""))[:10]]
reasons = Counter(str(r.get("reason", "unknown"))[:50] for r in today_rejs)
print(f"Total today: {len(today_rejs)}")
for r, n in reasons.most_common(5):
    print(f"  {n}x: {r[:80]}")

# 3. Strike sanity rejections
sanity_rejs = [r for r in today_rejs if "strike_sanity" in str(r.get("reason", ""))]
print(f"\n  of which strike_sanity rejections: {len(sanity_rejs)}")

# 4. Fills
print("\n--- Recent fills ---")
fills = []
with open(DCACHE / "trade_journal.jsonl", encoding="utf-8") as f:
    for line in f:
        try:
            r = json.loads(line)
            if r.get("event") == "FILL":
                fills.append(r)
        except Exception:
            pass
print(f"Total fills: {len(fills)}")
if fills:
    print(f"Latest fill: {fills[-1].get('ts', '?')[:19]}")
    print(f"Latest 3:")
    for f in fills[-3:]:
        print(f"  {f.get('ts', '?')[:19]} {f.get('side')} {f.get('symbol')} x{f.get('qty')} @ {f.get('avg_fill_price')} | {f.get('tag', '')}")

# 5. System audit
print("\n--- System audit ---")
try:
    sa = json.loads((DCACHE / "system_audit.json").read_text(encoding="utf-8"))
    for name, sub in sa.get("subsystems", {}).items():
        st = sub.get("status", "?")
        d = str(sub.get("details", ""))[:90]
        mark = {"ok": "[OK]", "warn": "[WARN]", "error": "[ERR]"}.get(st, "[?]")
        print(f"  {mark:6s} {name}: {d}")
except Exception as e:
    print(f"  err: {e}")
