import json

with open(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_actions.json', 'r', encoding='utf-8') as f:
    actions = json.load(f)
print('brain_actions.json:')
print(json.dumps(actions, indent=2))

with open(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json', 'r', encoding='utf-8') as f:
    state = json.load(f)
print()
print('brain_state.json top-level:')
print('  today_date:', state['today_date'])
print('  call_count_today:', state['call_count_today'])
print('  timestamp:', state['timestamp'])
print('  last_decision.ist_time:', state['last_decision']['ist_time'])
print('  last_decision.bias:', state['last_decision']['bias'])
print('  last_decision.actions:', state['last_decision']['actions'])
print('  last_decision.note:', state['last_decision']['note'])
print('  history[0].ist_time:', state['history'][0].get('ist_time'))
print('  history[1].ist_time:', state['history'][1].get('ist_time'))
print('  history len:', len(state['history']))
