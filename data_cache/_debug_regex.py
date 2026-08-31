import re
from pathlib import Path
p = Path(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json")
raw = p.read_text(encoding="utf-8")
# Show context around position 14780
print("---around 14780---")
print(repr(raw[14770:14800]))
print("---around end of file---")
print(repr(raw[-300:]))
# Find all '"last_updated_ist"' positions
for m in re.finditer(r'"last_updated_ist"', raw):
    print(f"last_updated_ist at {m.start()}: {raw[m.start():m.start()+40]!r}")
