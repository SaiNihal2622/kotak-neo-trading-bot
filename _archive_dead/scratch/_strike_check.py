"""Sanity check LLM strike selection vs current spot."""
import json
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))
now_ist = datetime.now(IST)
today = now_ist.strftime("%Y-%m-%d")

# Current spot per chain
ch_nifty = json.load(open("data_cache/option_chain_NIFTY.json"))
nifty_spot = ch_nifty["spot"]

# Today's OPEN decisions
opens = []
with open("data_cache/quant_service_decisions.jsonl", encoding="utf-8") as f:
    for line in f:
        try:
            r = json.loads(line)
            ts = r.get("ts", "")
            if today not in ts[:10]:
                continue
            d = r.get("decision", {})
            if d.get("type") == "OPEN":
                opens.append(r)
        except Exception:
            pass

print(f"Current NIFTY spot: {nifty_spot}")
print(f"Total OPEN decisions today: {len(opens)}")
print()
print(f"{'TIME':19s} {'STRATEGY':24s} {'STRIKES':30s} {'FROM SPOT':12s} {'STATUS'}")
print("-" * 100)
for r in opens:
    d = r.get("decision", {})
    ts = r.get("ts", "?")[:19]
    strat = (d.get("strategy") or "?")[:24]
    legs = d.get("legs", [])
    strikes = [f"{l.get('strike')}{l.get('opt_type', '?')}" for l in legs]
    strikes_str = ", ".join(strikes)[:30]
    if legs:
        avg_strike = sum(int(l.get("strike", 0)) for l in legs) / len(legs)
        from_spot = avg_strike - nifty_spot
        from_spot_str = f"{from_spot:+.0f}"
        status = "OK" if abs(from_spot) < 500 else "TOO FAR OTM!"
    else:
        from_spot_str = "?"
        status = "?"
    print(f"{ts} {strat:24s} {strikes_str:30s} {from_spot_str:12s} {status}")
