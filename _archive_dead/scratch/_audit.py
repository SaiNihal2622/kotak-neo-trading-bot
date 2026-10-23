"""Audit what's running for tomorrow."""
import subprocess
import urllib.request

print('=== WINDOWS SERVICES (NSSM) ===')
for svc in ['KotakBotPaper', 'KotakDashboard', 'KotakHttpServer', 'KotakQuantService']:
    r = subprocess.run(['C:\\Tools\\nssm\\nssm-2.24\\win32\\nssm.exe', 'status', svc],
                       capture_output=True, text=True)
    state = r.stdout.strip() or r.stderr.strip()
    print(f"  {svc:25s} status={state}")

print()
print('=== PYTHON PROCESSES ===')
import psutil
for p in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time']):
    if p.info['name'] == 'python.exe':
        cmdline = ' '.join(p.info['cmdline'] or [])
        if 'kotak' in cmdline.lower() or 'system' in cmdline.lower() or 'core' in cmdline.lower():
            print(f"  PID {p.info['pid']}: created={p.info['create_time']}")
            print(f"     cmd: {cmdline[:200]}")

print()
print('=== HTTP ENDPOINTS ===')
for url, name in [
    ('http://127.0.0.1:8510/healthz', 'core :8510'),
    ('http://127.0.0.1:8503/healthz', 'brain :8503'),
    ('http://127.0.0.1:8502/healthz', 'http_server :8502'),
]:
    try:
        r = urllib.request.urlopen(url, timeout=3)
        print(f"  {name}: {r.status} {r.read().decode()[:120]}")
    except Exception as e:
        print(f"  {name}: NOT REACHABLE ({e})")

print()
print('=== PAPER STATE ===')
import json
with open('data_cache/paper_state.json', 'r', encoding='utf-8') as f:
    s = json.load(f)
print(f"  cash: Rs.{s['cash']:,.2f}")
print(f"  realized_pnl: Rs.{s['realized_pnl']:,.2f}")
print(f"  open_positions: {len(s['positions'])}")
print(f"  total orders: {len(s['orders'])}")
print()
print('=== KOTAK SESSION ===')
try:
    with open('data_cache/kotak_prod_session.json', 'r', encoding='utf-8') as f:
        ses = json.load(f)
    print(f"  session: {ses.get('session_token', 'NONE')[:20]}...")
    print(f"  expires: {ses.get('expires_at', 'unknown')}")
except FileNotFoundError:
    print('  NO KOTAK SESSION FILE — bot will need to re-auth tomorrow')