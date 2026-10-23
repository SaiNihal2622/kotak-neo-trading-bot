import json
from pathlib import Path
p = Path('data_cache/liveness_crash.jsonl')
lines = p.read_text(encoding='utf-8').splitlines()
print('Total crash entries: ' + str(len(lines)))
print('=== Most recent 8 ===')
for line in lines[-8:]:
    try:
        j = json.loads(line)
        print('  ' + j.get('ts','')[:19] + ' | PID ' + str(j.get('pid','')) + ' | ' + str(j.get('reason','')) + ' | ' + str(j.get('signal_name','')) + ' | uptime ' + str(j.get('loop_uptime_sec', 0))[:5] + 's')
    except Exception as e:
        print('  parse err: ' + str(e))
