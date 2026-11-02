"""List kotak-related crons."""
import json, subprocess, sys
sys.path.insert(0, r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
r = subprocess.run(['mavis', 'cron', 'list'], capture_output=True, text=True)
data = json.loads(r.stdout)
for task in data.get("tasks", []):
    name = task.get("cronName", "")
    if "kotak" in name or "phase12" in name or "pre-flight" in name:
        cid = task.get("cronId", "")
        enabled = task.get("enabled", False)
        schedule = task.get("schedule", "")
        print(f"  {name} (enabled={enabled}) schedule={schedule} id={cid}")