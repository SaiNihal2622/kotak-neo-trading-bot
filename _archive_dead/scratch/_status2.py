"""Verify state after kill."""
import urllib.request
import psutil

try:
    r = urllib.request.urlopen('http://127.0.0.1:8510/healthz', timeout=3)
    print('core:', r.status, r.read().decode()[:120])
except Exception as e:
    print('core down:', e)

print('\nMy core + adapter processes:')
for p in psutil.process_iter(['pid', 'name', 'cmdline']):
    try:
        if p.info['name'] == 'python.exe':
            cmd = ' '.join(p.info['cmdline'] or [])
            if 'system.core' in cmd and 'minimax-agent' in cmd:
                print('  PID', p.info['pid'], ':', cmd[:100])
    except (psutil.NoSuchProcess, KeyError):
        pass