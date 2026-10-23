"""Strike choices the LLM has been making today."""
import json
import re
from collections import Counter
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))
today = datetime.now(IST).strftime("%Y-%m-%d")

strike_choices = Counter()
underlying_choices = Counter()
with open("data_cache/quant_service_decisions.jsonl", encoding="utf-8") as f:
    for line in f:
        try:
            r = json.loads(line)
            if today not in str(r.get("ts", ""))[:10]:
                continue
            d = r.get("decision", {})
            if d.get("type") != "OPEN":
                continue
            for leg in d.get("legs", []):
                strike = leg.get("strike", "")
                opt = leg.get("opt_type", "")
                if strike and opt:
                    strike_choices[(strike, opt)] += 1
                underlying_choices[d.get("underlying", "?")] += 1
        except Exception:
            pass

print(f"Underlyings the LLM traded today:")
for u, n in underlying_choices.most_common():
    print(f"  {n:3d}x  {u}")

print()
print(f"Top strike choices (strike, opt):")
for (strike, opt), n in strike_choices.most_common(20):
    print(f"  {n:3d}x  {strike}{opt}")

# NIFTY chain check
print()
ch = json.load(open("data_cache/option_chain_NIFTY.json"))
chain_keys = set()
for k in ch.get("strikes", {}).keys():
    parts = k.split("_")
    if len(parts) == 2:
        chain_keys.add((int(parts[0]), parts[1]))

nifty_in_chain = 0
nifty_out_chain = 0
for (strike, opt), n in strike_choices.items():
    if (strike, opt) in chain_keys:
        nifty_in_chain += n
    else:
        nifty_out_chain += n
print(f"NIFTY leg choices IN chain: {nifty_in_chain}")
print(f"NIFTY leg choices NOT in chain: {nifty_out_chain}")
