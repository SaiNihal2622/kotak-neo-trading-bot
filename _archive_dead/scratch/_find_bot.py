"""Find the bot process."""
import psutil
for p in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time']):
    if p.info['name'] == 'python.exe':
        cmd = ' '.join(p.info['cmdline'] or [])
        if 'kotak_bot' in cmd or 'main' in cmd:
            print(f"PID {p.info['pid']}: created={p.info['create_time']}")
            print(f"  cmd: {cmd[:300]}")