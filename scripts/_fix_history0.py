import json

FP = r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json"

with open(FP, "r", encoding="utf-8") as f:
    data = json.load(f)

# history[0] is the OLD last_decision that we just promoted (the 13:20 decision).
# Its ist_time was set to 13:25 due to my earlier edit; fix it back to 13:20.
h0 = data["history"][0]
if h0.get("ist_time") == "2026-08-31 13:25:00" and "13:20" in h0.get("decision_summary", ""):
    h0["ist_time"] = "2026-08-31 13:20:00"
    h0["ts"] = "2026-08-31T07:50:00Z"
    h0["timestamp"] = "2026-08-31T07:50:00Z"
    print("Fixed history[0] ist_time/ts back to 13:20 / 07:50Z")
else:
    print(f"history[0] not as expected: ist_time={h0.get('ist_time')}, summary starts with: {h0.get('decision_summary', '')[:80]}")

with open(FP, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print("history[0].ist_time:", data["history"][0]["ist_time"])
print("history[0].ts:", data["history"][0]["ts"])
print("history[1].ist_time:", data["history"][1].get("ist_time"))
