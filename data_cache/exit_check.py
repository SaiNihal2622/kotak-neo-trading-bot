import json
with open(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\trades_state.json") as f:
    state = json.load(f)
for tid, t in state["trades"].items():
    if t.get("opened_at", "").startswith("2026-08-13"):
        print(f"Trade {tid}:")
        print(f"  opened: {t['opened_at']}")
        print(f"  closed: {t.get('closed_at')}")
        print(f"  exit_reason: {t.get('exit_reason')}")
        print(f"  realized_pnl: {t.get('realized_pnl')}")
        print(f"  target_hit: {t.get('target_hit')}")
        print(f"  stop_hit: {t.get('stop_hit')}")
        print()
