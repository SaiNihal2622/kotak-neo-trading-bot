"""Honest improvement audit — what's actually wrong / could be better."""
import json
from collections import Counter
from pathlib import Path

ROOT = Path(".").resolve()


# 1. Duplicate fills
fills = []
with open(ROOT / "data_cache/trade_journal.jsonl", encoding="utf-8") as f:
    for line in f:
        try:
            r = json.loads(line)
            if r.get("event") == "FILL":
                key = (r.get("ts", "")[:19], r.get("symbol"), r.get("side"), r.get("qty"), r.get("avg_fill_price"))
                fills.append(key)
        except Exception:
            pass

cnt = Counter(fills)
dupes = {k: v for k, v in cnt.items() if v > 1}
print("=== 1. Duplicate fills ===")
print(f"  Total FILL entries: {len(fills)}")
print(f"  Duplicate rows: {sum(v - 1 for v in dupes.values())} extra entries across {len(dupes)} sets")
if dupes:
    print("  Sample dupes:")
    for k, v in list(dupes.items())[:3]:
        print(f"    {k} x{v}")


# 2. Phantom/suspect fills
phantom = 0
suspect = 0
with open(ROOT / "data_cache/trade_journal.jsonl", encoding="utf-8") as f:
    for line in f:
        try:
            r = json.loads(line)
            if r.get("phantom_price"):
                phantom += 1
            if r.get("suspect_price"):
                suspect += 1
        except Exception:
            pass
print()
print("=== 2. Phantom / suspect fills ===")
print(f"  phantom_price: {phantom}")
print(f"  suspect_price: {suspect}")


# 3. LLM HOLD ratio today
today = "2026-09-18"
holds = opens = closes = skips = total = 0
with open(ROOT / "data_cache/quant_service_decisions.jsonl", encoding="utf-8") as f:
    for line in f:
        if today not in line[:50]:
            continue
        try:
            r = json.loads(line)
            d = r.get("decision", {})
            t = d.get("type", "")
            if t:
                total += 1
            if t == "HOLD":
                holds += 1
            elif t == "OPEN":
                opens += 1
            elif t == "CLOSE":
                closes += 1
            elif t == "SKIP_DAY":
                skips += 1
        except Exception:
            pass
print()
print("=== 3. LLM today ===")
print(f"  Total: {total}")
if total:
    print(f"  HOLD: {holds} ({holds / total * 100:.0f}%)")
    print(f"  OPEN: {opens}, CLOSE: {closes}, SKIP_DAY: {skips}")


# 4. Rejections
rejs = []
with open(ROOT / "data_cache/order_rejections.jsonl", encoding="utf-8") as f:
    for line in f:
        try:
            rejs.append(json.loads(line))
        except Exception:
            pass
print()
print("=== 4. Order rejections ===")
print(f"  Total: {len(rejs)}")
if rejs:
    reasons = Counter(r.get("reason", "unknown") for r in rejs)
    print("  Top reasons:")
    for r, n in reasons.most_common(5):
        print(f"    {n}x: {r[:70]}")


# 5. Audit subsystems summary
sa = json.loads((ROOT / "data_cache/system_audit.json").read_text(encoding="utf-8"))
subs = sa.get("subsystems", {})
warns = [k for k, v in subs.items() if v.get("status") == "warn"]
errs = [k for k, v in subs.items() if v.get("status") == "error"]
print()
print("=== 5. Audit subsystems ===")
print(f"  WARN: {warns}")
print(f"  ERROR: {errs}")


# 6. Brain LLM HOLD-streak (consecutive HOLDs at end of log)
print()
print("=== 6. Last 5 decisions ===")
lines = (ROOT / "data_cache/quant_service_decisions.jsonl").read_text(encoding="utf-8").strip().split("\n")
for line in lines[-5:]:
    try:
        r = json.loads(line)
        d = r.get("decision", r)
        ts = r.get("ts", "?")[:19]
        t = d.get("type", "?")
        rat = str(d.get("rationale", ""))[:80]
        print(f"  {ts} {t}: {rat}...")
    except Exception:
        pass
