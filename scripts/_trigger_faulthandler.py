"""Trigger faulthandler on the launcher process via os.kill(SIGINT)."""
import os
import sys
import signal
import psutil

if len(sys.argv) < 2:
    print('Usage: _trigger_faulthandler.py <pid>')
    sys.exit(1)

target_pid = int(sys.argv[1])

print(f'Sending SIGINT to PID {target_pid}')
try:
    os.kill(target_pid, signal.SIGINT)
    print('SIGINT sent. Target should dump stack to stderr.')
except Exception as e:
    print(f'os.kill failed: {e}')
    # Try SIGBREAK on Windows
    try:
        os.kill(target_pid, signal.CTRL_BREAK_EVENT)
        print('CTRL_BREAK_EVENT sent')
    except Exception as e2:
        print(f'CTRL_BREAK_EVENT also failed: {e2}')

# Also check process state
try:
    p = psutil.Process(target_pid)
    print(f'Process still alive: {p.is_running()}, status: {p.status()}')
except Exception as e:
    print(f'Process dead: {e}')
