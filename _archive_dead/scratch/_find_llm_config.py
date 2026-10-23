"""Find LLM config in quant_service.py."""
from pathlib import Path
text = Path('scripts/quant_service.py').read_text(encoding='utf-8')
for i, line in enumerate(text.splitlines(), 1):
    if any(k in line for k in ('LLM_MAX_TOKENS', 'LLM_BASE', 'LLM_KEY', 'LLM_MODEL')):
        print(str(i).rjust(4) + ': ' + line.strip()[:180])
