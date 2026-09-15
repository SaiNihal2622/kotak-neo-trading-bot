"""Check today's P&L from trades_state.json."""
import json
d = json.load(open('data_cache/trades_state.json'))
trades = d.get('trades', {})
today = '2026-09-10'
total_today = 0
n = 0
for tid, t in trades.items():
    if t.get('status') != 'closed':
        continue
    ca = t.get('closed_at', '')
    if today in ca:
        pnl = t.get('realized_pnl', 0) or 0
        strat = t.get('plan', {}).get('strategy', 'unknown')
        total_today += pnl
        n += 1
        print(f"  {tid}  {strat}  pnl=Rs.{pnl:+.0f}  closed_at={ca}")
print(f"\nTotal today: {n} closed trades, pnl=Rs.{total_today:+.0f}")
