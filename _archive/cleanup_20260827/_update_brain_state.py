import json
from pathlib import Path

p = Path(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json")
data = json.loads(p.read_text(encoding="utf-8"))

actions_path = Path(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_actions.json")
actions = json.loads(actions_path.read_text(encoding="utf-8"))

data["last_decision"] = actions
data["call_count_today"] = int(data.get("call_count_today", 0)) + 1

p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"Updated. call_count_today={data['call_count_today']}, last_decision.ist_time={data['last_decision']['ist_time']}")
