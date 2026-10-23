"""Current state check."""
import json
from datetime import datetime

# Check live state
with open('data_cache/paper_state.json', 'r', encoding='utf-8') as f:
    s = json.load(f)
now = datetime.now().strftime('%Y-%m-%d %H:%M')
print(f'=== CURRENT STATE ({now}) ===')
print(f"Cash: Rs.{s['cash']:,.2f}")
print(f"Realized P&L: Rs.{s['realized_pnl']:,.2f}")
print(f"Open positions: {len(s['positions'])}")
for sym, pos in s['positions'].items():
    print(f"  {sym}: qty={pos['qty']} avg=Rs.{pos['avg_price']:.2f} ltp=Rs.{pos['ltp']:.2f} pnl=Rs.{pos.get('pnl', 0):,.0f}")

# Check liveness
with open('data_cache/liveness.json', 'r') as f:
    lv = json.load(f)
print(f"Bot PID: {lv.get('pid')}")
print(f"Bot uptime: {lv.get('uptime_sec')}s ({lv.get('uptime_sec')/3600:.1f}h)")
print(f"VIX: {lv.get('snapshot', {}).get('vix'):.2f}")
print(f"Snapshot ts: {lv.get('snapshot', {}).get('ts')}")

# Check live_go status
with open('data_cache/live_go_status.json', 'r') as f:
    lgs = json.load(f)
print('\\n=== LIVE-GO STATUS ===')
cur = lgs.get('current', {})
print(f"streak: {cur.get('consecutive_green_days')}/10")
print(f"cumulative_pnl: Rs.{cur.get('cumulative_pnl_rs', 0):,.2f}")
print(f"return: {cur.get('cumulative_return_pct', 0):.2f}%")
print(f"avg_daily_pnl: Rs.{cur.get('avg_daily_pnl_rs', 0):,.2f}")
print(f"total_trades: {cur.get('total_trades')}")