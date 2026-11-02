"""Test brain_daemon watchdog mode via subprocess."""
import subprocess, sys, os
env = os.environ.copy()
env['PYTHONIOENCODING'] = 'utf-8'
env['BRAIN_DAEMON_MODE'] = 'watchdog'
env['KOTAK_BRAIN_INTERVAL'] = '10'
script = '''
import asyncio, os, sys
from pathlib import Path
sys.path.insert(0, r"C:\\\\Users\\\\saini\\\\.minimax-agent\\\\projects\\\\kotak-neo-bot")
from system.brain.brain_daemon import BrainDaemon
import json

async def main():
    bd = BrainDaemon.__new__(BrainDaemon)
    bd.data_dir = Path(r"C:\\\\Users\\\\saini\\\\.minimax-agent\\\\projects\\\\kotak-neo-bot\\\\data_cache")
    print("watchdog starting for 30s...", flush=True)
    task = asyncio.create_task(bd.run_forever())
    await asyncio.sleep(30)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

asyncio.run(main())
print("done")
'''
r = subprocess.run(
    [sys.executable, '-c', script],
    capture_output=True, text=True,
    cwd=r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot',
    env=env,
    timeout=45,
)
print('exit:', r.returncode)
print('stdout:', r.stdout[-1500:])
if r.stderr:
    print('stderr:', r.stderr[-1500:])

# Check heartbeat
hb_path = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\heartbeat_brain_daemon.json')
if hb_path.exists():
    data = json.loads(hb_path.read_text(encoding='utf-8'))
    print(f'heartbeat: {data}')