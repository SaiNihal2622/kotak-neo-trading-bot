"""Find Sep 17 orders in paper_state."""
import json
state = json.load(open("data_cache/paper_state.json"))
orders = state.get("orders", {})
sep17_orders = []
for oid, o in orders.items():
    fa = o.get("filled_at", "") or ""
    if "2026-09-17" in fa[:10]:
        sep17_orders.append((oid, o))
print(f"Sep 17 orders in paper_state: {len(sep17_orders)}")
for oid, o in sep17_orders[:20]:
    sym = o.get("symbol", "")
    side = o.get("side", "")
    qty = o.get("qty", 0)
    px = o.get("avg_fill_price", 0)
    fa = (o.get("filled_at") or "")[:19]
    print(f"  {oid[:18]} | {side} {sym} x{qty} @ {px} | filled={fa}")
