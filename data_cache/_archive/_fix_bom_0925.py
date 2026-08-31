"""Strip BOM from brain_state.json so send_trader_tg.py (utf-8 read) can parse it."""
from pathlib import Path
p = Path(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json")
raw = p.read_bytes()
if raw.startswith(b"\xef\xbb\xbf"):
    p.write_bytes(raw[3:])
    print("BOM stripped OK")
else:
    print("no BOM present (raw first 8 bytes: %r)" % raw[:8])
