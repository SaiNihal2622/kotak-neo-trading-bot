"""Dedupe brain_state.json history and add 13:55 slim mirror at top."""
import json
from pathlib import Path

p = Path(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json")
s = json.loads(p.read_text(encoding="utf-8"))

new_top = {
    "ts": "2026-08-31T08:25:00Z",
    "ist_time": "2026-08-31 13:55:00",
    "bias": "cautious",
    "source": "mavis",
    "max_positions": 0,
    "actions": [],
    "note": "intraday_post_1330_cutoff_no_new_entries_terminal_hold",
}

# Dedupe by (ts, ist_time), keep first occurrence
seen = set()
deduped = []
for entry in [new_top] + s.get("history", []):
    key = (entry.get("ts"), entry.get("ist_time"))
    if key in seen:
        continue
    seen.add(key)
    deduped.append(entry)

s["history"] = deduped[:25]
p.write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding="utf-8")

print("history len:", len(s["history"]))
print("history[0]:", s["history"][0])
print("history[1]:", s["history"][1])
print("history[2]:", s["history"][2])
