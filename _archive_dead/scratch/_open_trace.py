"""Trace today's OPEN decisions — did they reach the bot? Did they fill?"""
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30))
now_ist = datetime.now(IST)
today = now_ist.strftime("%Y-%m-%d")

print(f"=== Today's OPEN decisions — execution trace ===\n")

# 1. Today's OPEN decisions from LLM
opens = []
with open("data_cache/quant_service_decisions.jsonl", encoding="utf-8") as f:
    for line in f:
        try:
            r = json.loads(line)
            ts = r.get("ts", "")
            if today not in ts[:10]:
                continue
            d = r.get("decision", {})
            if d.get("type") != "OPEN":
                continue
            opens.append(r)
        except Exception:
            pass

print(f"Total OPEN decisions today: {len(opens)}")
print()

# 2. quant_actions.json — what did the bot actually see?
print("=== bot-side: quant_actions.json / quant_actions.failed.json ===")
qa_path = Path("data_cache/quant_actions.json")
qaf_path = Path("data_cache/quant_actions.failed.json")
qa_actions = []
if qa_path.exists():
    try:
        qa = json.loads(qa_path.read_text(encoding="utf-8"))
        if isinstance(qa, dict):
            qa_actions = qa.get("actions", []) or []
    except Exception:
        pass
qaf_actions = []
if qaf_path.exists():
    try:
        qaf = json.loads(qaf_path.read_text(encoding="utf-8"))
        if isinstance(qaf, list):
            qaf_actions = qaf
    except Exception:
        pass

print(f"Current quant_actions.json: {len(qa_actions)} actions")
if qa_actions:
    for a in qa_actions[-3:]:
        print(f"  {a.get('ts', '?')[:19]} | {a.get('type', '?')} | placed_legs={a.get('placed_legs', '?')}")
print(f"Failed actions history: {len(qaf_actions)} actions")
if qaf_actions:
    print("Last 3 failed:")
    for a in qaf_actions[-3:]:
        print(f"  {a.get('ts', '?')[:19]} | {a.get('strategy', '?')[:30]} | reason={str(a.get('failed_reason', '?'))[:60]}")

# 3. Today's fills
print()
print("=== Today's fills ===")
fills = []
with open("data_cache/trade_journal.jsonl", encoding="utf-8") as f:
    for line in f:
        try:
            r = json.loads(line)
            ts = r.get("ts", "")
            if today not in ts[:10]:
                continue
            if r.get("event") == "FILL":
                fills.append(r)
        except Exception:
            pass
print(f"Total fills today: {len(fills)}")
for f in fills:
    print(f"  {f.get('ts', '?')[:19]} | {f.get('side')} {f.get('symbol')} x{f.get('qty')} @ {f.get('avg_fill_price')} | delta={f.get('realized_delta', 0)} | tag={f.get('tag', '?')}")

# 4. Sample 3 recent OPEN decisions and show their legs
print()
print("=== Last 5 OPEN decisions ===")
for r in opens[-5:]:
    d = r.get("decision", {})
    legs = d.get("legs", [])
    print(f"\n  {r.get('ts', '?')[:19]} {d.get('strategy', '?')[:30]}")
    print(f"    rationale: {str(d.get('rationale', ''))[:160]}...")
    for leg in legs[:4]:
        print(f"    leg: {leg.get('side')} {leg.get('strike')}{leg.get('opt_type', '')} qty={leg.get('qty')} @ {leg.get('price')} ({leg.get('order_type', '?')})")
