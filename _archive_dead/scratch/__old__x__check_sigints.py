import json
from pathlib import Path
p = Path('data_cache/liveness_crash.jsonl')
lines = p.read_text(encoding='utf-8').splitlines()
print('=== SIGINT events today (2026-09-22) ===')
count = 0
for line in lines:
    try:
        j = json.loads(line)
        ts = j.get('ts', '')
        if '2026-09-22' in ts:
            sig = j.get('signal_name', '')
            pid = j.get('pid', '')
            reason = j.get('reason', '')
            uptime = j.get('loop_uptime_sec', 0)
            print('  ' + ts[:19] + ' | PID ' + str(pid).rjust(6) + ' | reason=' + reason + ' | uptime=' + str(round(uptime, 0)) + 's')
            count += 1
    except:
        pass
print('Total today: ' + str(count))
