"""Fix remaining daily popup-spawning tasks. These only fire ~once/day but
still pop up when they do. Not strictly 'every minute' but worth fixing
so the user can keep working without surprise windows.

Tasks fixed:
  - CryptoOptionsBotDailyMaintenance: python.exe -> pythonw.exe via the same
    run_hidden.bat launcher that health_check.py uses (same pattern, same reliability)
  - CryptoOptionsBotDailyReset: add -WindowStyle Hidden to powershell invocation
"""
import json
import urllib.request

BRAIN_URL = "http://localhost:8503/command"


def brain_run(cmd_list, timeout=20):
    body = json.dumps({'cmd': 'run', 'command': cmd_list, 'timeout': timeout}).encode('utf-8')
    req = urllib.request.Request(BRAIN_URL, data=body, method='POST',
                                  headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout + 5) as r:
        return json.loads(r.read().decode('utf-8'))


def delete_then_create(name, exe, args, schedule_args):
    """Delete + recreate a scheduled task as SYSTEM with hidden launcher."""
    print(f'\n=== {name} ===')
    out = brain_run(['schtasks.exe', '/delete', '/tn', name, '/f'], timeout=15)
    print(f"  delete: exit={out.get('exit')} stdout={out.get('stdout','').strip()[:80]}")
    cmd = ['schtasks.exe', '/create', '/tn', name, '/tr', f'{exe} {args}',
           '/ru', 'SYSTEM', '/rl', 'HIGHEST', '/f'] + schedule_args
    out = brain_run(cmd, timeout=15)
    print(f"  create: exit={out.get('exit')} stderr={out.get('stderr','').strip()[:200]}")


# 1. DailyMaintenance: switch to run_hidden.bat launcher (uses pythonw.exe).
#    This is the SAME launcher that CryptoOptionsBotHealthCheck already uses,
#    so we know it's silent and correctly redirects stdout/stderr to the log.
delete_then_create(
    'CryptoOptionsBotDailyMaintenance',
    'C:\\Users\\saini\\.minimax-agent\\projects\\crypto-options-bot\\scripts\\run_hidden.bat',
    'C:\\Users\\saini\\.minimax-agent\\projects\\crypto-options-bot\\scripts\\daily_maintenance.py C:\\Users\\saini\\.minimax-agent\\projects\\crypto-options-bot\\logs\\maintenance.out.log',
    ['/sc', 'daily', '/st', '06:00'],
)

# 2. DailyReset: add -WindowStyle Hidden to powershell invocation.
delete_then_create(
    'CryptoOptionsBotDailyReset',
    'powershell.exe',
    '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "C:\\Users\\saini\\.minimax-agent\\projects\\crypto-options-bot\\daily_reset.ps1"',
    ['/sc', 'daily', '/st', '00:30'],
)

# Verify
print('\n=== VERIFICATION ===')
for n in ('CryptoOptionsBotDailyMaintenance', 'CryptoOptionsBotDailyReset'):
    out = brain_run(['schtasks.exe', '/query', '/tn', n, '/fo', 'list', '/v'], timeout=15)
    lines = (out.get('stdout', '') or '').split('\n')
    relevant = [ln for ln in lines if 'Task To Run' in ln or 'Run As User' in ln]
    print(f'\n{n}:')
    for ln in relevant:
        print(f'  {ln.strip()}')
