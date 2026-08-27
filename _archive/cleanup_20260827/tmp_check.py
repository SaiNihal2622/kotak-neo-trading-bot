import json
import os
import sys

base = r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache"
paper_path = os.path.join(base, "paper_state.json")
trades_path = os.path.join(base, "trades_state.json")

print("=== PAPER STATE ===")
try:
    with open(paper_path, "r") as f:
        s = json.load(f)
    print(f"  cash        = {s.get('cash')}")
    print(f"  realized    = {s.get('realized_pnl')}")
    print(f"  positions   = {len(s.get('positions', {}))}")
    print(f"  orders      = {len(s.get('orders', {}))}")
    print(f"  trades      = {len(s.get('trades', {}))}")
    print(f"  capital     = {s.get('capital') or s.get('cash', 0) + s.get('realized_pnl', 0)}")
    # show last modified mtime
    import os
    mt = os.path.getmtime(paper_path)
    import time
    print(f"  mtime_local = {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(mt))}")
except Exception as e:
    print(f"  ERROR: {e}")

print()
print("=== TRADES STATE ===")
try:
    with open(trades_path, "r") as f:
        t = json.load(f)
    open_trades = []
    if isinstance(t, dict):
        for tid, v in t.items():
            if isinstance(v, dict) and v.get("status") == "open":
                open_trades.append((tid, v.get("underlying"), v.get("leg_count"), v.get("pnl"), v.get("entry_time")))
    elif isinstance(t, list):
        for v in t:
            if isinstance(v, dict) and v.get("status") == "open":
                open_trades.append((v.get("id"), v.get("underlying"), v.get("leg_count"), v.get("pnl"), v.get("entry_time")))
    print(f"  total trades     = {len(t) if isinstance(t, (list, dict)) else 'unknown'}")
    print(f"  open trades      = {len(open_trades)}")
    for tid, und, lc, pnl, et in open_trades[:6]:
        print(f"    {tid}: {und} legs={lc} pnl={pnl} entry={et}")
    import os
    mt = os.path.getmtime(trades_path)
    import time
    print(f"  mtime_local      = {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(mt))}")
except Exception as e:
    print(f"  ERROR: {e}")
