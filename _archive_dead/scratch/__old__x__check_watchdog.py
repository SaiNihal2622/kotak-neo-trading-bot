"""Check nssm_watchdog.py uses print vs logging."""
import sys
sys.path.insert(0, r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
sys.path.insert(0, r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\scripts')
import nssm_watchdog
src = open(nssm_watchdog.__file__, encoding='utf-8').read()
print('uses print:', 'print(' in src)
print('uses logging:', 'logging' in src)
print('writes to file:', 'open(' in src)
print('uses print(...) for tick info:', src.count('print('))
# find print calls
import re
for m in re.finditer(r'print\([^)]*\)', src):
    print('  PRINT:', m.group(0)[:120])
