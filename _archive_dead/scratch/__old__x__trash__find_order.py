"""Find Order constructor lines."""
with open('kotak_bot/__main__.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()
for i, line in enumerate(lines):
    if 'exchange="NFO"' in line:
        print(f"L{i+1}: {line.rstrip()}")