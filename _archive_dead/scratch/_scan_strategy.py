"""Scan strategy_library.py for relevant lines."""
lines = open('scripts/strategy_library.py', encoding='utf-8').readlines()
for i, line in enumerate(lines, 1):
    if 'def ' in line or 'candles' in line or '.get(' in line:
        print(f'{i}: {line.rstrip()}')
