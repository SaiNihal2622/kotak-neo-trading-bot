"""Find and replace _anti_template_check + _system_enforcement_check body."""
from pathlib import Path
import re
p = Path('scripts/quant_service.py')
content = p.read_text(encoding='utf-8')

# Replace _anti_template_check with no-op stub
old_func = re.search(
    r'def _anti_template_check\(.*?\):\s*\n    """[^"]*?FIX 2026-09-09 15:50.*?"""\s*\n.*?(?=\ndef |\Z)',
    content, re.DOTALL
)
if old_func:
    print(f'_anti_template_check span: {old_func.start()}-{old_func.end()}')

# Just locate it
m = content.find('def _anti_template_check(')
print(f'_anti_template_check starts at: {m}')
n = content.find('\n\ndef ', m + 10)
print(f'next def starts at: {n}')
print('preview:')
print(content[m:n][:500])
