import json, re
p = r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json'
with open(p, 'rb') as f:
    data = f.read()
keys_seen = {}
pattern = re.compile(rb'"([A-Za-z_][A-Za-z0-9_]*)"\s*:')
for m in pattern.finditer(data):
    k = m.group(1).decode()
    if k in keys_seen:
        keys_seen[k].append(m.start())
    else:
        keys_seen[k] = [m.start()]
dups = {k: v for k, v in keys_seen.items() if len(v) > 1}
for k, positions in dups.items():
    print(f'duplicate key: {k} at byte positions {positions}')
    for pos in positions:
        line = data[:pos].count(b'\n') + 1
        ctx = data[max(0, pos - 30):pos + 80]
        print(f'  line {line}: {ctx!r}')
