#!/usr/bin/env python
"""Retroactively scrub old decision log entries that have 'Already long X' / 'Still long X' etc.

FIX 2026-09-02 11:50: clean up decisions log that have hallucinated claims
from before the scrubber was in place. We replace the rationale text with
a [SCRUBBED] marker so the LLM knows the previous text was unreliable.
"""
import sys, json, re
from pathlib import Path
ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
log = ROOT / 'data_cache' / 'quant_service_decisions.jsonl'

bad_patterns = [
    (r"(?i)already long [^\.\,\n]+", "[no live position]"),
    (r"(?i)already short [^\.\,\n]+", "[no live position]"),
    (r"(?i)still long [^\.\,\n]+", "[no live position]"),
    (r"(?i)still short [^\.\,\n]+", "[no live position]"),
    (r"(?i)already (?:entered|opened|initiated) [^\.\,\n]+", "[trade was not filled]"),
    (r"(?i)i (?:am|'m) (?:long|short|holding) [^\.\,\n]+", "[no live position]"),
    (r"(?i)my (?:existing|open) (?:long|short|position) [^\.\,\n]+", "[no live position]"),
]

if not log.exists():
    print('no log file')
    sys.exit(0)

lines = log.read_text(encoding='utf-8').splitlines()
scrubbed = 0
out = []
for line in lines:
    if not line.strip():
        out.append(line)
        continue
    try:
        rec = json.loads(line)
    except Exception:
        out.append(line)
        continue
    dec = rec.get('decision', {}) or {}
    rat = dec.get('rationale', '') or ''
    new = rat
    for pat, repl in bad_patterns:
        new = re.sub(pat, repl, new)
    if new != rat:
        dec['rationale'] = new
        dec['rationale_scrubbed_retroactively'] = True
        scrubbed += 1
    out.append(json.dumps(rec, ensure_ascii=False))

log.write_text('\n'.join(out) + '\n', encoding='utf-8')
print(f'scrubbed {scrubbed} decisions')
