"""Inspect venv python (launcher) process via brain to find what it's doing."""
import sys
sys.path.insert(0, '.')
from pathlib import Path
from datetime import datetime

# The launcher pid and the actual bot pid
launcher_pid = 17584  # venv python
bot_pid = 24608       # SYSTEM python

print('=== Time:', datetime.now().isoformat())
print('=== Looking at launcher pid:', launcher_pid)

# Try psutil
try:
    import psutil
    p = psutil.Process(launcher_pid)
    print(f'  Status: {p.status()}')
    print(f'  Num threads: {p.num_threads()}')
    print(f'  Memory: {p.memory_info().rss / 1024 / 1024:.1f} MB')
    print(f'  CPU%: {p.cpu_percent(interval=0.1):.1f}')
    print(f'  Open files (first 30):')
    try:
        of = p.open_files()
        for f in of[:30]:
            print(f'    {f.path}')
    except Exception as e:
        print(f'    (access denied: {e})')
    print(f'  Threads:')
    for t in p.threads()[:10]:
        print(f'    tid={t.id} cpu_time={t.user_time + t.system_time:.2f}s')
    print(f'  Connections (first 5):')
    try:
        for c in p.connections(kind='inet')[:5]:
            print(f'    {c.laddr} -> {c.raddr} ({c.status})')
    except Exception as e:
        print(f'    (no connections)')
except Exception as e:
    print(f'  psutil error: {e}')

# Now try the bot
print()
print('=== Looking at actual bot pid:', bot_pid)
try:
    import psutil
    p = psutil.Process(bot_pid)
    print(f'  Status: {p.status()}')
    print(f'  Num threads: {p.num_threads()}')
    print(f'  Memory: {p.memory_info().rss / 1024 / 1024:.1f} MB')
    print(f'  CPU%: {p.cpu_percent(interval=0.1):.1f}')
except Exception as e:
    print(f'  psutil error: {e}')
