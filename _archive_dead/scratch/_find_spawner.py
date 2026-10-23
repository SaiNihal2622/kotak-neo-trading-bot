"""Find any process that spawns kotak_bot paper."""
from pathlib import Path

for f in Path('kotak_bot').rglob('*.py'):
    text = f.read_text(encoding='utf-8', errors='replace')
    for i, line in enumerate(text.splitlines(), 1):
        lower = line.lower()
        if 'subprocess' in lower and ('kotak_bot' in lower or '-m kotak' in lower or 'python.exe' in lower):
            stripped = line.strip()
            if stripped.startswith('#') or stripped.startswith('"""') or stripped.startswith("'"):
                continue
            print(str(f) + ':' + str(i) + ' -> ' + stripped[:200])
