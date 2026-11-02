"""Quick status check."""
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30))
n = datetime.now(IST)

ps_path = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\paper_state.json')
if ps_path.exists():
    s = json.loads(ps_path.read_text(encoding='utf-8'))
    print(f'PAPER STATE:')
    print(f'  cash: {s.get("cash")}')
    print(f'  realized_pnl: {s.get("realized_pnl")}')
    print(f'  positions: {len(s.get("positions", {}))}')
    print(f'  orders: {len(s.get("orders", {}))}')

liv_path = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\liveness.json')
if liv_path.exists():
    l = json.loads(liv_path.read_text(encoding='utf-8'))
    snap = l.get('snapshot', {})
    print(f'\nLIVENESS (legacy bot):')
    print(f'  pid: {l.get("pid")}')
    print(f'  uptime_sec: {l.get("uptime_sec"):.0f}')
    print(f'  state: {l.get("state")}')
    print(f'  capital: {snap.get("capital")}')
    print(f'  vix: {snap.get("vix"):.2f}')
    print(f'  is_paused: {snap.get("is_paused")}')
    print(f'  trades_today: {snap.get("trades_today")}')
    print(f'  realized_pnl: {snap.get("realized_pnl")}')

print(f'\nTIME:')
print(f'  now: {n.strftime("%Y-%m-%d %H:%M:%S")} ({n.strftime("%A")})')
print(f'  market open: {"yes" if 9 <= n.hour <= 15 and n.weekday() < 5 else "no"}')
print(f'  force-square window (after 14:30): {"yes" if (n.hour > 14 or (n.hour == 14 and n.minute >= 30)) else "no"}')
print(f'  EOD window (15:15-15:25): {"yes" if n.hour == 15 and 15 <= n.minute <= 25 else "no"}')