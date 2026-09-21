"""Fix remaining popup-spawning scheduled tasks.

Steps (run via brain :8503 /command endpoint so it has admin):
  1. Delete the popup-producing tasks
  2. Recreate them with /ru SYSTEM + /rl HIGHEST + hidden launcher

Tasks fixed (all run every 1 minute which was driving the user nuts):
  - CryptoOptionsBotHeartbeat (powershell.exe -File heartbeat.ps1)         -> +WindowStyle Hidden, /ru SYSTEM
  - CryptoOptionsBotWatchdog (powershell.exe -File watchdog.ps1)           -> +WindowStyle Hidden, /ru SYSTEM
  - kotak-nssm-watchdog    (python.exe scripts/nssm_watchdog.py)            -> pythonw.exe, /ru SYSTEM

Tasks already fixed in earlier sessions (left alone):
  - KotakBotHealthcheck (every 5 min)
  - KotakBotWakeForMarket (daily 08:00)
  - CryptoOptionsBotHealthCheck (uses run_hidden.bat already)
  - CryptoOptionsBotDailyMaintenance (Python, daily)
  - CryptoOptionsBotDailyReset (disabled)

Tasks NOT touched (different concerns):
  - kotak-pre-market-self-heal (08:25 daily, hidden via run_hidden.bat already)
  - kotak-eod-pnl-evaluator (15:30 daily)
  - kotak-nightly-state-backup (23:00 daily)
  - KotakHttpServer-Autostart (logon only)
  - KotakSupervisor (already running, do not disturb)
"""
import json
import urllib.request

BRAIN_URL = "http://localhost:8503/command"

# Helper to invoke a system command via brain endpoint as SYSTEM.
# brain command has timeout 10s default; pass longer for schtasks queries.
def brain_run(cmd_list, timeout=20):
    body = json.dumps({'cmd': 'run', 'command': cmd_list, 'timeout': timeout}).encode('utf-8')
    req = urllib.request.Request(
        BRAIN_URL, data=body, method='POST',
        headers={'Content-Type': 'application/json'},
    )
    with urllib.request.urlopen(req, timeout=timeout + 5) as r:
        return json.loads(r.read().decode('utf-8'))


def delete_then_create(name, exe, args, schedule_args, ps_logon=False):
    """Delete + recreate a scheduled task to switch to hidden / SYSTEM."""
    print(f'\n=== {name} ===')
    # 1. Delete
    out = brain_run(['schtasks.exe', '/delete', '/tn', name, '/f'], timeout=15)
    print(f"  delete: exit={out.get('exit')} stdout={out.get('stdout','').strip()[:80]}")
    # 2. Recreate
    cmd = ['schtasks.exe', '/create', '/tn', name, '/tr', f'{exe} {args}',
           '/ru', 'SYSTEM', '/rl', 'HIGHEST', '/f'] + schedule_args
    out = brain_run(cmd, timeout=15)
    print(f"  create: exit={out.get('exit')} stderr={out.get('stderr','').strip()[:200]}")


# 1. CryptoOptionsBotHeartbeat - powershell.exe with hidden flag + SYSTEM
delete_then_create(
    'CryptoOptionsBotHeartbeat',
    'powershell.exe',
    '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "C:\\Users\\saini\\.minimax-agent\\projects\\crypto-options-bot\\heartbeat.ps1"',
    ['/sc', 'minute', '/mo', '1'],
)

# 2. CryptoOptionsBotWatchdog - same fix
delete_then_create(
    'CryptoOptionsBotWatchdog',
    'powershell.exe',
    '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "C:\\Users\\saini\\.minimax-agent\\projects\\crypto-options-bot\\watchdog.ps1"',
    ['/sc', 'minute', '/mo', '1'],
)

# 3. kotak-nssm-watchdog - pythonw.exe (GUI subsystem, NO console at all) + SYSTEM
delete_then_create(
    'kotak-nssm-watchdog',
    'C:\\Users\\saini\\.minimax-agent\\projects\\kotak-neo-bot\\.venv\\Scripts\\pythonw.exe',
    'C:\\Users\\saini\\.minimax-agent\\projects\\kotak-neo-bot\\scripts\\nssm_watchdog.py',
    ['/sc', 'minute', '/mo', '1'],
)

# Verify all 3 are now hidden / using pythonw / running as SYSTEM
print('\n=== VERIFICATION ===')
for n in ('CryptoOptionsBotHeartbeat', 'CryptoOptionsBotWatchdog', 'kotak-nssm-watchdog'):
    out = brain_run(['schtasks.exe', '/query', '/tn', n, '/fo', 'list', '/v'], timeout=15)
    lines = (out.get('stdout', '') or '').split('\n')
    relevant = [ln for ln in lines if 'Task To Run' in ln or 'Run As User' in ln or 'hidden' in ln.lower()]
    print(f'\n{n}:')
    for ln in relevant:
        print(f'  {ln.strip()}')
