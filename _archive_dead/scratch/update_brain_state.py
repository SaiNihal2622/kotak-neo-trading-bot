import json

bs = r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json'
ba = r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_actions.json'

# Load with strict=False (the file has duplicate keys in nested objects which is fine)
with open(bs, 'r', encoding='utf-8') as f:
    state = json.load(f, strict=False)
with open(ba, 'r', encoding='utf-8') as f:
    new_dec = json.load(f, strict=False)

# Append compact history record
hist_entry = {
    'ts': new_dec['ts'],
    'ist_time': new_dec['ist_time'],
    'bias': new_dec['bias'],
    'actions_count': len(new_dec.get('actions', [])),
    'note': new_dec.get('note', '')
}
state['last_decision'] = new_dec
state.setdefault('history', []).append(hist_entry)
state['call_count_today'] = state.get('call_count_today', 0) + 1
state['last_updated_ist'] = new_dec['ist_time']

with open(bs, 'w', encoding='utf-8') as f:
    json.dump(state, f, ensure_ascii=False, indent=2)
print('updated', bs)
print('call_count_today =', state['call_count_today'])
print('history_len =', len(state['history']))
print('last_decision ist_time =', state['last_decision']['ist_time'])
print('last_decision note =', state['last_decision']['note'])
