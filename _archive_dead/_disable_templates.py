"""Replace the 3 enforcement functions with clean no-op stubs."""
from pathlib import Path
import re

p = Path('scripts/quant_service.py')
src = p.read_text(encoding='utf-8')

NOOP = '''def {name}(context: dict) -> dict | None:
    """FIX 2026-09-17: REMOVED. The user requested no static templates and full
    24/7 LLM-driven dynamics. The LLM is the SOLE decision-maker; if it says
    HOLD, the bot honors HOLD. The LLM is re-prompted every cycle with fresh
    data, so any genuine edge that emerges is picked up within minutes.

    Returns None (no enforcement).
    """
    return None'''

# Identify line ranges of the 3 functions by parsing
import ast
tree = ast.parse(src)
fn_ranges = {}
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name in ('_strategy_library_enforcement', '_anti_template_check', '_system_enforcement_check'):
        fn_ranges[node.name] = (node.lineno, node.end_lineno)

lines = src.split('\n')

# Replace each range with the no-op stub. Process in REVERSE order so
# earlier line numbers remain valid as we edit later ones.
for name in ('_system_enforcement_check', '_anti_template_check', '_strategy_library_enforcement'):
    start, end = fn_ranges[name]
    stub = NOOP.format(name=name)
    new_lines = lines[:start-1] + stub.split('\n') + lines[end:]
    lines = new_lines

p.write_text('\n'.join(lines), encoding='utf-8')

# Identify line ranges of the 3 functions by parsing
import ast
tree = ast.parse(src)
fn_ranges = {}
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name in ('_strategy_library_enforcement', '_anti_template_check', '_system_enforcement_check'):
        fn_ranges[node.name] = (node.lineno, node.end_lineno)

lines = src.split('\n')  # list of lines

# Replace each range with the no-op stub. Process in REVERSE order so
# earlier line numbers remain valid as we edit later ones.
for name in ('_system_enforcement_check', '_anti_template_check', '_strategy_library_enforcement'):
    start, end = fn_ranges[name]
    stub = NOOP.format(name=name)
    # Replace lines[start-1:end] with stub lines
    new_lines = lines[:start-1] + stub.split('\n') + lines[end:]
    lines = new_lines

p.write_text('\n'.join(lines), encoding='utf-8')

# Verify
import ast as _ast
tree2 = _ast.parse(p.read_text(encoding='utf-8'))
for node in _ast.walk(tree2):
    if isinstance(node, _ast.FunctionDef) and node.name in ('_strategy_library_enforcement', '_anti_template_check', '_system_enforcement_check'):
        is_noop = (
            len(node.body) == 1
            and isinstance(node.body[0], _ast.Return)
            and isinstance(node.body[0].value, _ast.Constant)
            and node.body[0].value.value is None
        )
        print(f'{node.name}: {"OK no-op" if is_noop else "still has body, BROKEN"}')

# Verify tests still pass
print('Running tests...')
import subprocess
r = subprocess.run(
    [str(Path('.venv/Scripts/python.exe')), '-m', 'pytest', 'tests/', '-q', '--tb=line', '-x'],
    cwd=str(p.parent.parent.resolve()), capture_output=True, text=True, timeout=180
)
print(r.stdout[-2000:])
print('STDERR:', r.stderr[-500:])
