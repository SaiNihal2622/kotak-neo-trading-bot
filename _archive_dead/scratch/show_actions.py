p = r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_actions.json'
with open(p, 'r', encoding='utf-8') as f:
    text = f.read()
for i, line in enumerate(text.split('\n'), 1):
    print(f'{i:3}: {line}')
