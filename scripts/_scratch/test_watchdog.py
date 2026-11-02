"""Test brain_daemon BRAIN_DAEMON_MODE=watchdog directly (no NSSM needed)."""
import asyncio
import os
import sys
from pathlib import Path

PROJECT_ROOT = r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot'
sys.path.insert(0, PROJECT_ROOT)

# Set watchdog mode BEFORE importing brain_daemon
os.environ['BRAIN_DAEMON_MODE'] = 'watchdog'
os.environ['KOTAK_BRAIN_INTERVAL'] = '10'  # 10s for fast test

from system.brain.brain_daemon import BrainDaemon

async def main():
    print("=== Testing BRAIN_DAEMON_MODE=watchdog ===")
    bd = BrainDaemon.__new__(BrainDaemon)
    bd.data_dir = Path(PROJECT_ROOT) / 'data_cache'

    # Run watchdog for ~30 seconds
    print("Starting watchdog mode for 30s...")
    task = asyncio.create_task(bd.run_forever())
    await asyncio.sleep(30)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    print("Watchdog mode test complete")

asyncio.run(main())

# Check heartbeat
import json
hb_path = Path(PROJECT_ROOT) / 'data_cache' / 'heartbeat_brain_daemon.json'
if hb_path.exists():
    data = json.loads(hb_path.read_text(encoding='utf-8'))
    print(f"\nHeartbeat: {data}")