import json
from pathlib import Path

p = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json')
data = json.loads(p.read_text(encoding='utf-8'))

# Load the new decision from brain_actions.json
actions_p = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_actions.json')
new_decision = json.loads(actions_p.read_text(encoding='utf-8'))

# Update top-level fields
data['today_date'] = '2026-08-31'
data['call_count_today'] = data.get('call_count_today', 0) + 1
data['timestamp'] = '2026-08-31T06:50:00Z'

# Replace last_decision
data['last_decision'] = new_decision

# Atomic write
p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')

new_size = p.stat().st_size
cc = data['call_count_today']
nb = new_decision['bias']
na = len(new_decision['actions'])
print(f'OK: brain_state.json updated, size={new_size} bytes, call_count_today={cc}, last_decision bias={nb}, actions={na}')
