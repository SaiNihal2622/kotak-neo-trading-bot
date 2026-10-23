"""Check bot log for set_broker + tick flow."""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
with open('Logs/bot_stderr.log', 'rb') as f:
    raw = f.read()
text = raw.decode('utf-8', errors='replace')
lines = text.split('\n')
recent = lines[-100:]
for line in recent:
    if any(k in line for k in ['set_broker', 'LIVE-FEED', 'broker set', 'replayed', 'broker is None', '14:4', '14:5']):
        print(line[:200])