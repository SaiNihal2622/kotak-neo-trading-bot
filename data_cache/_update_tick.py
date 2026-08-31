"""Update brain_state.json: bump call_count, replace last_decision, preserve history."""
import json
from pathlib import Path

p = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json')
state = json.loads(p.read_text(encoding='utf-8-sig'))

new_decision = json.loads(
    Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_actions.json').read_text(encoding='utf-8')
)

state['call_count_today'] = state.get('call_count_today', 0) + 1
state['last_decision'] = new_decision
state['last_updated_ist'] = '2026-08-26 10:11:48'

p.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding='utf-8')
print(f"OK: call_count_today={state['call_count_today']}")
print(f"OK: bias={state['last_decision']['bias']} actions={len(state['last_decision']['actions'])} note={state['last_decision']['note']}")
