"""Sum of unique fills in journal."""
import json
with open("data_cache/trade_journal.jsonl", encoding="utf-8") as f:
    fills = [json.loads(l) for l in f if l.strip()]
inline = [r for r in fills if r.get("event") == "FILL" and not r.get("phantom_price")]

seen = set()
total = 0.0
for f in inline:
    sym = f.get("symbol", "")
    side = f.get("side", "")
    ts = str(f.get("ts", ""))[:10]
    delta = f.get("realized_delta", 0) or 0
    if not sym or not side or not ts:
        continue
    if side == "SELL":
        key = (sym, "SELL", ts)
    else:
        key = (sym, "BUY", f.get("qty", 0), round(float(f.get("avg_fill_price", 0) or 0), 2), ts)
    if key in seen:
        continue
    seen.add(key)
    total += delta
ps = json.load(open("data_cache/paper_state.json"))
paper = ps["realized_pnl"]
print(f"Sum of unique fills (post-dedup): Rs.{total:,.2f}")
print(f"paper_state.realized_pnl: Rs.{paper:.2f}")
print(f"Missing from journal: Rs.{paper - total:+,.2f}")
