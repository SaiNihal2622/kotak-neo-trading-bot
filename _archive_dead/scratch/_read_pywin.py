from pathlib import Path
text = Path('.venv/Lib/site-packages/pywin32_bootstrap.py').read_text(encoding='utf-8', errors='replace')
print(text[:3000])
