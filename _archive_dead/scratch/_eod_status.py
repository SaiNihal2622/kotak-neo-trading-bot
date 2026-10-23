"""EOD status snapshot."""
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30))
today = datetime.now(IST).strftime("%Y-%m-%d")
print(f"Today: {today} IST (market close 15:30)\n")

# Today's fills
fills = []
with open("data_cache/trade_journal.jsonl", encoding="utf-8") as f:
    for line in f:
        try:
            r = json.loads(line)
            if today in str(r.get("ts", ""))[:10] and r.get("event") == "FILL":
                fills.append(r)
        except Exception:
            pass

print(f"=== TODAY FILLS ({len(fills)}) ===")
for f in fills:
    sym = f.get("symbol", "")
    side = f.get("side", "")
    qty = f.get("qty", 0)
    px = f.get("avg_fill_price", 0)
    delta = f.get("realized_delta", 0) or 0
    tag = f.get("tag", "")
    print(f"  {f.get('ts', '?')[:19]} | {side} {sym} x{qty} @ Rs.{px} | delta=Rs.{delta:+.2f} | {tag}")

# Today's decisions
opens = []
holds = 0
with open("data_cache/quant_service_decisions.jsonl", encoding="utf-8") as f:
    for line in f:
        try:
            r = json.loads(line)
            if today not in str(r.get("ts", ""))[:10]:
                continue
            d = r.get("decision", {})
            t = d.get("type", "")
            if t == "OPEN":
                opens.append(r)
            elif t == "HOLD":
                holds += 1
        except Exception:
            pass
print(f"\n=== TODAY DECISIONS ===")
print(f"  OPEN attempts: {len(opens)}")
print(f"  HOLD: {holds}")

# Rejections
rejs = []
with open("data_cache/order_rejections.jsonl", encoding="utf-8") as f:
    for line in f:
        try:
            r = json.loads(line)
            if today in str(r.get("ts", ""))[:10]:
                rejs.append(r)
        except Exception:
            pass
print(f"  Rejections: {len(rejs)}")

# Account
state = json.load(open("data_cache/paper_state.json"))
print(f"\n=== ACCOUNT ===")
print(f"  Cash: Rs.{state.get('cash', 0):,.2f}")
print(f"  Realized P&L: Rs.{state.get('realized_pnl', 0):,.2f}")
print(f"  Open positions: {len(state.get('positions', {}))}")

# EOD evaluation just ran
print(f"\n=== EOD EVAL (just ran at 15:30) ===")
import os
if os.path.exists("data_cache/strategy_performance.json"):
    sp = json.load(open("data_cache/strategy_performance.json"))
    bd = sp.get("by_day", {}).get(today, {})
    print(f"  by_day[{today}]: {bd.get('pnl', 0):+,.2f} ({bd.get('trades', 0)} trades)")
    print(f"  Phantom meta: {sp.get('phantom', {})}")
