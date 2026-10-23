from pathlib import Path
p = Path('tests/test_anti_template.py')
src = p.read_text(encoding='utf-8')
# More leftover assertions to remove
src = src.replace(
    '        assert result is None\n        assert result["actions"][0]["type"] == "OPEN"',
    '        assert result is None'
)
p.write_text(src, encoding='utf-8')

# Final test
import subprocess
r = subprocess.run(
    ['.venv/Scripts/python.exe', '-m', 'pytest', 'tests/', '-q', '--tb=line'],
    cwd=str(p.parent.parent.resolve()), capture_output=True, text=True, timeout=300
)
print(r.stdout[-2000:])
print('STDERR:', r.stderr[-200:])
