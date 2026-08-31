import json
from pathlib import Path

state_path = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json')
actions_path = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_actions.json')

# Load new decision
with open(actions_path, 'r', encoding='utf-8') as f:
    new_decision = json.load(f)

# Load current state
with open(state_path, 'r', encoding='utf-8') as f:
    state = json.load(f)

# Update last_decision and call_count_today
old_decision = state.get('last_decision', {})
state['last_decision'] = new_decision
state['call_count_today'] = state.get('call_count_today', 0) + 1

# Add to history
if 'history' not in state:
    state['history'] = []
state['history'].append({
    'ist_time': new_decision['ist_time'],
    'bias': new_decision['bias'],
    'note': new_decision.get('note', ''),
    'actions': new_decision.get('actions', [])
})

# Write back
with open(state_path, 'w', encoding='utf-8') as f:
    json.dump(state, f, indent=2, ensure_ascii=False)

print('OK. call_count_today:', state['call_count_today'], '| history length:', len(state['history']))
print('Old ts:', old_decision.get('ist_time'), '-> New ts:', new_decision['ist_time'])
print('Bias:', new_decision['bias'], '| Actions:', len(new_decision.get('actions', [])))
