"""Test brain_daemon watchdog mode — capture both stdout and stderr."""
import sys, os, asyncio, traceback
sys.path.insert(0, r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
os.environ['BRAIN_DAEMON_MODE'] = 'watchdog'
os.environ['KOTAK_BRAIN_INTERVAL'] = '5'

from pathlib import Path
import json
from system.brain.brain_daemon import BrainDaemon

async def main():
    bd = BrainDaemon.__new__(BrainDaemon)
    bd.data_dir = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache')
    print('watchdog starting for 15s...')
    task = asyncio.create_task(bd.run_forever())
    await asyncio.sleep(15)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

try:
    asyncio.run(main())
except Exception as e:
    print(f'OUTER ERROR: {type(e).__name__}: {e}')
    traceback.print_exc()
print('done')

hb_path = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\heartbeat_brain_daemon.json')
if hb_path.exists():
    data = json.loads(hb_path.read_text(encoding='utf-8'))
    print(f'final heartbeat: status={data.get("status")} ts={data.get("ts")}')