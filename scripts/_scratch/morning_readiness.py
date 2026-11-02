"""Morning readiness check."""
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys

sys.path.insert(0, r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
from system.brain.brain_daemon import _next_weekly_expiry, _days_to_expiry, _now_ist

now = _now_ist()
print(f'NOW IST: {now.strftime("%Y-%m-%d %H:%M:%S")} ({now.strftime("%A")})')
print(f'Days to expiry: {_days_to_expiry(now)}')
print(f'Expiry date: {_next_weekly_expiry(now).strftime("%Y-%m-%d")}')

tomorrow = now + timedelta(days=1)
print(f'\nTOMORROW: {tomorrow.strftime("%Y-%m-%d %H:%M:%S")} ({tomorrow.strftime("%A")})')
print(f'Weekday: {tomorrow.weekday() < 5}')
print(f'Days to expiry tomorrow: {_days_to_expiry(tomorrow)}')

# Paper state
ps_path = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\paper_state.json')
if ps_path.exists():
    s = json.loads(ps_path.read_text(encoding='utf-8'))
    print(f'\nPAPER STATE:')
    print(f'  cash: {s.get("cash")}')
    print(f'  realized_pnl: {s.get("realized_pnl")}')
    print(f'  positions: {len(s.get("positions", {}))}')
    print(f'  orders: {len(s.get("orders", {}))}')
    print(f'  ts: {s.get("ts", "unknown")}')

# Liveness
liv_path = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\liveness.json')
if liv_path.exists():
    l = json.loads(liv_path.read_text(encoding='utf-8'))
    snap = l.get('snapshot', {})
    print(f'\nLIVENESS:')
    print(f'  pid: {l.get("pid")}')
    print(f'  uptime_sec: {l.get("uptime_sec"):.0f}')
    print(f'  state: {l.get("state")}')
    print(f'  tick: {l.get("tick")}')
    print(f'  capital: {snap.get("capital")}')
    print(f'  vix: {snap.get("vix"):.2f}')
    print(f'  is_paused: {snap.get("is_paused")}')

# Brain daemon
hb_path = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\heartbeat_brain_daemon.json')
if hb_path.exists():
    h = json.loads(hb_path.read_text(encoding='utf-8'))
    print(f'\nBRAIN DAEMON:')
    print(f'  pid: {h.get("pid")}')
    print(f'  started_at: {h.get("started_at")}')
    print(f'  uptime_sec: {h.get("uptime_sec")}')
    print(f'  status: {h.get("status")}')
    print(f'  cycles: {h.get("counters", {}).get("cycles")}')

# Learning state
ls_path = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\learning_state.json')
if ls_path.exists():
    ls = json.loads(ls_path.read_text(encoding='utf-8'))
    g = ls.get('global', {})
    print(f'\nLEARNING STATE:')
    print(f'  total trades: {g.get("n")}')
    print(f'  win_rate: {g.get("win_rate", 0)*100:.1f}%')
    print(f'  sum_pnl: {g.get("sum_pnl")}')
    print(f'  sharpe_est: {g.get("sharpe_estimate")}')