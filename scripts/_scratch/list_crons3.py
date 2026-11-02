import subprocess, json, sys
r = subprocess.run(['mavis', 'cron', 'list'], capture_output=True, text=True)
try:
    data = json.loads(r.stdout)
except Exception as e:
    print(f'parse error: {e}')
    print('raw stdout:', r.stdout[:500])
    sys.exit(1)
for t in data.get('tasks', []):
    name = t.get('cronName', '')
    if 'kotak' in name.lower() or 'phase12' in name.lower() or 'pre-flight' in name.lower():
        cid = t.get('cronId', '')
        enabled = t.get('enabled', False)
        schedule = t.get('schedule', '')
        print(f"  {name} enabled={enabled} schedule={schedule} id={cid}")