"""Inspect the trades in trades_state.json to understand the reconcile gap."""
import json

ts = json.loads(open(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\trades_state.json", encoding="utf-8").read())
for tid, t in ts["trades"].items():
    plan_underlying = (t.get("plan") or {}).get("underlying", "?")
    print(f"{tid} underlying={plan_underlying} closed_at={t.get('closed_at')} realized_pnl={t.get('realized_pnl')}")
    for o in t.get("orders", []):
        print(f"  {o['symbol']} side={o['side']} qty={o.get('qty')} price={o.get('price')} avg_fill_price={o.get('avg_fill_price')} status={o.get('status')}")
