"""Check BROKEN-CONDOR messages."""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
with open('Logs/bot_stderr.log', 'rb') as f:
    raw = f.read()
text = raw.decode('utf-8', errors='replace')
lines = text.split('\n')
recent = lines[-100:]
for line in recent:
    if 'BROKEN-CONDOR' in line or 'broken-condor' in line.lower():
        print(line[:200])