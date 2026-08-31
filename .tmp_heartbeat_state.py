import json, os
from datetime import datetime, timezone, timedelta
path = "data_cache/heartbeat_state.json"
IST = timezone(timedelta(hours=5, minutes=30))
now = datetime.now(IST)
state = {}
if os.path.exists(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            state = json.load(f)
    except Exception:
        state = {}
state["last_tick"] = now.strftime("%Y-%m-%dT%H:%M:%S%z")
state["err"] = 0
state["tc"] = 0
state["alive4"] = 3
state["aliveAll"] = 3
state["dash"] = 200
state["mktHours"] = False
state["action"] = "silent"
state["botPids"] = [10640, 13352, 20216]
state["botAgeMin"] = 10
state["logSize"] = 724257
state["logAgeMin"] = 1892
state["lastErrLines"] = []
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, "w", encoding="utf-8") as f:
    json.dump(state, f, indent=2, ensure_ascii=False)
print("State updated.")
