"""Inspect the paper_state.json + trades_state.json to understand the reconcile gap."""
import json

ps = json.loads(open(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\paper_state.json", encoding="utf-8").read())
ts = json.loads(open(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\trades_state.json", encoding="utf-8").read())
print("=== PAPER_STATE ===")
print(f"  cash:                {ps.get('cash')}")
print(f"  realized_pnl:        {ps.get('realized_pnl')}")
print(f"  orders:              {len(ps.get('orders', {}))}")
print(f"  open_positions key:  {'positions' in ps}, type={type(ps.get('positions')).__name__}")
positions = ps.get('positions', {})
if isinstance(positions, dict):
    print(f"  positions count:     {len(positions)}")
    if positions:
        sample_sym = next(iter(positions))
        sample = positions[sample_sym]
        print(f"  sample key:          {sample_sym}")
        print(f"  sample value type:   {type(sample).__name__}")
        print(f"  sample value:        {sample}")
elif isinstance(positions, list):
    print(f"  positions list:      {len(positions)}")
    if positions:
        print(f"  sample:              {positions[0]}")
print()
print("=== TRADES_STATE ===")
print(f"  top-level keys: {list(ts.keys())}")
trades = ts.get("trades", {})
if isinstance(trades, dict):
    print(f"  trades count: {len(trades)}")
    for tid, t in trades.items():
        print(f"    {tid} status={t.get('status')} underlying={t.get('underlying')} pnl={t.get('pnl')} orders={len(t.get('orders', []))}")
elif isinstance(trades, list):
    print(f"  trades list: {len(trades)}")
    for t in trades:
        print(f"    {t.get('trade_id')} status={t.get('status')} underlying={t.get('underlying')} pnl={t.get('pnl')} orders={len(t.get('orders', []))}")
