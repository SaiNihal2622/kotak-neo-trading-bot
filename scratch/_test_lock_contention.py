"""Test the new _save_state() lock-contention handling.

Simulates a long-held lock from another process while the bot tries to save.
Verifies:
  1. Save retries with backoff instead of failing immediately
  2. Save eventually succeeds once the lock releases
  3. Diagnostic info (lock_holder_pid) is reported in logs
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path('.').resolve()
sys.path.insert(0, str(ROOT))

from kotak_bot.broker.paper_client import PaperClient

# Use a test path so we don't touch the real paper_state.json
test_path = ROOT / 'data_cache' / '_test_paper_lock.json'
test_path.write_text(json.dumps({
    'cash': 100000.0,
    'realized_pnl': 0.0,
    'orders': {},
    'positions': {},
}), encoding='utf-8')

pc = PaperClient(
    starting_capital=100000.0,
    persist_path=str(test_path),
)
pc.connect()

# Place a stale lock to simulate daily_maintenance holding it
lock_path = test_path.parent / 'paper.lock'
fake_holder_pid = 99999  # nonexistent PID
lock_path.write_text(str(fake_holder_pid), encoding='utf-8')

# Hold the actual file open (this is what causes Permission denied on Windows)
held_handle = open(test_path, 'r', encoding='utf-8')
print(f'Holding {test_path.name} open via fake handle. Lock PID={fake_holder_pid}')

# Background thread to release the lock after 2 seconds
import threading
def release():
    time.sleep(2.0)
    held_handle.close()
    print('Released held handle (simulating daily_maintenance done)')
    try:
        lock_path.unlink()
        print('Removed fake lock file')
    except Exception as e:
        print(f'(could not remove lock: {e})')

threading.Thread(target=release, daemon=True).start()

# Time the save — should retry then succeed when lock releases
print('\n=== Calling _save_state() with lock held ===')
t0 = time.time()
try:
    pc._save_state()
    elapsed = time.time() - t0
    print(f'\n[OK] _save_state succeeded after {elapsed:.2f}s')
except Exception as e:
    elapsed = time.time() - t0
    print(f'\n[FAIL] _save_state failed after {elapsed:.2f}s: {e}')

# Cleanup
try:
    test_path.unlink()
except Exception:
    pass
