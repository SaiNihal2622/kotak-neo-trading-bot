"""Dump the Python stack trace of a running Python process via Win32 API.

Uses NtQueryInformationThread to enumerate threads, then sends a CTRL_BREAK_EVENT
to the process which causes Python to write a stack trace to stderr.

For this to work, the target process must be a child of a console that supports
CTRL_BREAK_EVENT. Most Python processes spawned by NSSM don't have a console.
"""
import sys
import os
import ctypes
from ctypes import wintypes

GENERATE_CONSOLE_BREAK_EVENT = 0x1

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

AttachConsole = kernel32.AttachConsole
AttachConsole.argtypes = [wintypes.DWORD]
AttachConsole.restype = wintypes.BOOL

FreeConsole = kernel32.FreeConsole
FreeConsole.argtypes = []
FreeConsole.restype = wintypes.BOOL

GenerateConsoleCtrlEvent = kernel32.GenerateConsoleCtrlEvent
GenerateConsoleCtrlEvent.argtypes = [wintypes.DWORD, wintypes.DWORD]
GenerateConsoleCtrlEvent.restype = wintypes.BOOL

GetConsoleWindow = kernel32.GetConsoleWindow
GetConsoleWindow.argtypes = []
GetConsoleWindow.restype = wintypes.HWND

target_pid = int(sys.argv[1])

# Strategy: write a faulthandler trigger to the target's stdin.
# Actually simpler: use GenerateConsoleCtrlEvent to send CTRL_BREAK_EVENT.
# Python's faulthandler is auto-installed if --X faulthandler or PYTHONFAULTHANDLER=1.

# Try attaching to a console first
print(f'Attaching to console of PID {target_pid}...')
ok = AttachConsole(target_pid)
print(f'AttachConsole returned: {ok}, last error: {ctypes.get_last_error()}')

if not ok:
    print('No console to attach to. Target process likely has no console (NSSM-spawned).')
    print('Try setting PYTHONFAULTHANDLER=1 in the bot env and restart.')
    sys.exit(1)

# Send CTRL_BREAK_EVENT to wake up Python's faulthandler
print(f'Sending CTRL_BREAK_EVENT to {target_pid}...')
ok = GenerateConsoleCtrlEvent(GENERATE_CONSOLE_BREAK_EVENT, target_pid)
print(f'GenerateConsoleCtrlEvent returned: {ok}')

FreeConsole()
print('Done. Check the target process stderr for the stack dump.')
