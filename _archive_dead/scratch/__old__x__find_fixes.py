"""Find FIX occurrences."""
with open('kotak_bot/__main__.py', 'r', encoding='utf-8') as f:
    main_py = f.read()
positions = []
i = 0
while True:
    i = main_py.find('FIX 2026-09-29 19:45', i)
    if i < 0:
        break
    positions.append(i)
    i += 1
print(f'Total occurrences: {len(positions)}')
for pos in positions:
    line = main_py.count('\n', 0, pos) + 1
    nearby = main_py[pos:pos+1500]
    print(f'\nL{line}:')
    for line_text in nearby.split('\n'):
        if 'exit_reason' in line_text:
            print(f'  {line_text.strip()[:100]}')