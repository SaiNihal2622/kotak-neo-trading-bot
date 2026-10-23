import json
ps = json.load(open('data_cache/paper_state.json'))
print('=== paper_state ===')
print(f"  cash          = Rs.{ps.get('cash', 0):,.2f}")
print(f"  realized_pnl  = Rs.{ps.get('realized_pnl', 0):+,.2f}")
print(f"  positions     = {len(ps.get('positions', {}))}")
for sym, pos in ps.get('positions', {}).items():
    print(f'    {sym}: qty={pos.get("qty")}, avg={pos.get("avg_price")}')
print()
# Live-go status
lgs = json.load(open('data_cache/live_go_status.json'))
print('=== live_go_status ===')
print(f"  streak        = {lgs['current']['consecutive_green_days']}/{lgs['policy']['min_consecutive_green_days']}")
print(f"  cumulative    = {lgs['current']['cumulative_return_pct']:+.2f}% (need +{lgs['policy']['min_cumulative_return_pct']}%)")
print(f"  avg daily PnL = Rs.{lgs['current']['avg_daily_pnl_rs']:+,.2f} / Rs.{lgs['policy']['min_avg_daily_pnl_rs']:,.2f}")
print(f"  total trades  = {lgs['current']['total_trades']}/{lgs['policy']['min_total_trades']}")
print(f"  gates         = {lgs['current']['gates_status']}")
print(f"  ready         = {lgs['ready_for_live']}")
print(f"  missing       = {lgs['missing_to_ready']}")
print()
# System audit
sa = json.load(open('data_cache/system_audit.json'))
print('=== system_audit ===')
print(f"  overall       = {sa.get('overall')}")
for k, v in (sa.get('subsystems', {}) or {}).items():
    if isinstance(v, dict):
        status = v.get('status', '?')
        detail = v.get('details', '')[:100]
        print(f'  {k:30s} {status:6s} {detail}')
print()
# Liveness
ls = json.load(open('data_cache/liveness.json'))
print('=== liveness ===')
print(f"  uptime_sec    = {ls.get('uptime_sec')}")
print(f"  tick          = {ls.get('tick')}")
print(f"  main_thread   = {ls.get('main_thread_alive')}")
print(f"  paused        = {ls.get('paused')}")