p = r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_actions.json'
with open(p, 'rb') as f:
    data = f.read()
print('size:', len(data))
print('first 50:', data[:50])
print('last 50:', data[-50:])
opens = data.count(b'{')
closes = data.count(b'}')
print('open braces:', opens, 'close braces:', closes)
print('byte 2495-2510:', repr(data[2495:2510]))
print('byte 2400-2500:', repr(data[2400:2500]))
