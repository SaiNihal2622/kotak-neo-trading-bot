import re
import json

with open(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json', 'r', encoding='utf-8') as f:
    content = f.read()

# Find all 'history' key occurrences
matches = [(m.start(), m.group()) for m in re.finditer(r'"history"\s*:\s*', content)]
print('history key positions:')
for pos, _ in matches:
    snippet = content[pos:pos+80].replace('\n', '\\n')
    print(f'  pos={pos}: {snippet}')

# Try json.loads with strict=False
try:
    data = json.loads(content, strict=False)
    print('Loaded OK, top-level type:', type(data).__name__)
    if isinstance(data, dict):
        print('top-level keys:', list(data.keys()))
except Exception as e:
    print('Load failed:', e)
