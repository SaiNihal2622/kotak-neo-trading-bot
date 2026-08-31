#!/usr/bin/env python3
"""Find ID mismatches between live_dashboard.py HTML and JavaScript."""
import re

PATH = r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\scripts\live_dashboard.py'
with open(PATH, 'r', encoding='utf-8') as f:
    src = f.read()

# Find all $('...') references in the JS
js_ids = set(re.findall(r"\$\('([a-zA-Z_]\w*)'\)", src))

# Find all id="..." in the HTML
html_ids = set(re.findall(r'id="([a-zA-Z_]\w*)"', src))

# JS uses something not in HTML
print("=== JS references with NO matching HTML id (will TypeError) ===")
for jid in sorted(js_ids):
    if jid not in html_ids:
        print(f"  $('{jid}')  <-- MISSING in HTML")

print("\n=== HTML ids NOT used by JS (just info, harmless) ===")
for hid in sorted(html_ids):
    if hid not in js_ids:
        print(f"  id='{hid}'")

# Find the specific renderKv call after the botKv, to see if thesisKv, marketKv, etc are misused
print("\n=== Looking for the bug: thesisKv vs brainKv ===")
for line_num, line in enumerate(src.split('\n'), 1):
    if 'thesisKv' in line or 'marketKv' in line or 'brainKv' in line:
        print(f"  L{line_num}: {line.rstrip()[:140]}")
