"""Find the bot process."""
import psutil
for p in psutil.process_iter(['pid', 'name', 'cmdline']):
    try:
        if p.info['name'] == 'python.exe':
            cmd = ' '.join(p.info['cmdline'] or [])
            if 'kotak_bot' in cmd and '__main__' in cmd:
                print('Bot PID:', p.info['pid'])
                print('  cmd:', cmd[:200])
    except (psutil.NoSuchProcess, KeyError):
        pass