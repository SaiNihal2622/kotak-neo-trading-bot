"""Trace Sep 15 +43,967 — was it real cash movement or RECON?"""
import json
from collections import Counter
from pathlib import Path

qp = Path("data_cache/trade_journal.jsonl")

print("=" * 70)
print("ALL JOURNAL ENTRIES ON SEP 15")
print("=" * 70)
with qp.open(encoding="utf-8") as f:
    for line in f:
        try:
            r = json.loads(line)
            ts = str(r.get("ts", ""))
            if "2026-09-15" not in ts[:10]:
                continue
            keys = list(r.keys())
            ti = str(r.get("trade_id", "?"))[:40]
            tag = r.get("tag", "")
            status = r.get("status", "")
            event = r.get("event", "")
            pnl = r.get("realized_pnl", 0) or 0
            delta = r.get("realized_delta", 0) or 0
            sym = r.get("symbol", "")
            px = r.get("avg_fill_price", 0) or r.get("exit_ltp", 0)
            side = r.get("side", "")
            qty = r.get("qty", 0)
            print(f"  ts={ts[:19]} | event={event:5s} status={status:20s} | trade_id={ti}")
            print(f"    sym={sym} {side} x{qty} @ {px} | tag={tag}")
            print(f"    realized_delta={delta} | realized_pnl={pnl}")
            print()
        except Exception as e:
            print(f"  parse err: {e}")

print("=" * 70)
print("PAPER STATE ORDERS ON SEP 15")
print("=" * 70)
state = json.load(open("data_cache/paper_state.json"))
for oid, o in state.get("orders", {}).items():
    pa = o.get("placed_at", "")
    if "2026-09-15" in pa:
        sym = o.get("symbol", "")
        side = o.get("side", "")
        st = o.get("status", "")
        px = o.get("avg_fill_price", 0)
        print(f"  {oid[:18]} | {side} {sym} | status={st} | placed={pa[:19]} | filled={str(o.get('filled_at', ''))[:19]} | px={px}")
