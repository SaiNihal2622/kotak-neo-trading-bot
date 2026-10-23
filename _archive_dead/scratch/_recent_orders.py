"""Check orders placed since restart."""
import json
state = json.load(open("data_cache/paper_state.json"))
orders = state.get("orders", {})

# Find orders placed since the restart (after 14:10 IST)
restart_ist_str = "14:10:00"
recent = []
for oid, o in orders.items():
    pa = o.get("placed_at", "") or ""
    if restart_ist_str in pa:
        recent.append((oid, o))

print(f"Orders placed since 14:10 IST restart: {len(recent)}")
for oid, o in recent[:10]:
    sym = o.get("symbol", "")
    side = o.get("side", "?")
    st = o.get("status", "?")
    px = o.get("avg_fill_price", 0)
    pa = str(o.get("placed_at", "?"))[:19]
    fa = str(o.get("filled_at", "?") or "NEVER")[:19]
    rej = str(o.get("rejection_reason", ""))[:80]
    print(f"  {oid[:20]} | {side} {sym} | st={st} px={px} | placed={pa} | filled={fa} | rej={rej}")
