"""Check recent bot activity."""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
with open('Logs/bot_stderr.log', 'rb') as f:
    raw = f.read()
text = raw.decode('utf-8', errors='replace')
lines = text.split('\n')
recent_lines = lines[-50:]
for line in recent_lines:
    if any(k in line for k in ['BROKEN', 'MAVIS-FORCE', 'broken', '14:1', '14:2', '14:3']):
        print(line[:200])