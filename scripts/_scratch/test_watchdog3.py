"""Test brain_daemon watchdog mode (process pool)."""
import sys, os
sys.path.insert(0, r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')

os.environ['BRAIN_DAEMON_MODE'] = 'watchdog'
os.environ['KOTAK_BRAIN_INTERVAL'] = '5'

import asyncio
from pathlib import Path
import json
from system.brain.brain_daemon import BrainDaemon

async def main():
    bd = BrainDaemon.__new__(BrainDaemon)
    bd.data_dir = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache')
    print('watchdog starting for 15s...', flush=True)
    task = asyncio.create_task(bd.run_forever())
    await asyncio.sleep(15)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

asyncio.run(main())
print('done')

hb_path = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\heartbeat_brain_daemon.json')
if hb_path.exists():
    data = json.loads(hb_path.read_text(encoding='utf-8'))
    print(f'final heartbeat: {data}')