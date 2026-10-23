"""Find 15:15 IST events in bot log."""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
with open('Logs/bot_stderr.log', 'rb') as f:
    raw = f.read()
text = raw.decode('utf-8', errors='replace')
lines = text.split('\n')
# Filter for entries around 09:45 UTC = 15:15 IST
for line in lines:
    if '09:4' in line[:25] or '15:14' in line[:25] or '15:15' in line[:25] or '15:16' in line[:25]:
        if any(k in line for k in ['CLOSE', 'auto', 'force', 'ORPHAN', 'square', 'close_trade', 'tp_', 'sl_']):
            print(line[:250])