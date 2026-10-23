import psutil
for p in psutil.process_iter(['pid', 'create_time', 'cmdline']):
    try:
        cmd = ' '.join(p.info['cmdline'] or [])
        if '__main__' in cmd or 'run_paper' in cmd:
            print('PID:', p.info['pid'], 'created:', p.info['create_time'])
            print('  cmd:', cmd[:200])
    except Exception:
        pass