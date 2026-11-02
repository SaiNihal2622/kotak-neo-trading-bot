"""Send SIGINT to a process to trigger Python's faulthandler stack dump."""
import os
import sys
import signal
import time

if len(sys.argv) < 2:
    print('Usage: _dump_stack.py <pid>')
    sys.exit(1)

target = int(sys.argv[1])
print(f'Sending SIGINT to PID {target} at {time.strftime("%H:%M:%S")}...')
try:
    os.kill(target, signal.SIGINT)
    print('SIGINT sent')
except Exception as e:
    print(f'Failed: {e}')
time.sleep(2)
print('Done. Check target stderr for stack dump.')
