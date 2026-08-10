"""Read bot log and show stats."""
import re
from collections import Counter
from pathlib import Path

log = Path("bot_stderr.log").read_text(encoding="utf-8", errors="ignore")
lines = log.splitlines()
print(f"Total log lines: {len(lines)}")
print(f"First line: {lines[0][:120]}")
print(f"Last line: {lines[-1][:120]}")
print()
# Strip ANSI
clean = [re.sub(r'\x1b\[[0-9;]*m', '', l).replace('\u20b9', 'Rs.') for l in lines]
# Count by level
levels = Counter()
for l in clean:
    m = re.search(r'\| (\w+)\s+\|', l)
    if m:
        levels[m.group(1)] += 1
print("Log levels:", dict(levels))
print()
# Last 15 lines
print("=== Last 15 lines ===")
for l in clean[-15:]:
    print(f"  {l[:160]}")
print()
# Errors
errs = [l for l in clean if 'Traceback' in l or 'FATAL' in l or 'ERROR' in l]
print(f"Total errors: {len(errs)}")
if errs:
    print("=== Last 3 errors ===")
    for e in errs[-3:]:
        print(f"  {e[:200]}")
# Look for main loop activity
scans = [l for l in clean if 'scanning' in l.lower() or 'selected:' in l.lower() or 'Executed plan' in l]
print(f"\nScans/trades in log: {len(scans)}")
if scans:
    print("Last 5:")
    for s in scans[-5:]:
        print(f"  {s[:160]}")
