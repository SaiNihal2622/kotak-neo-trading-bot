import sys
sys.path.insert(0, '.')
import json
from dashboard.real_provider import RealDataProvider
p = RealDataProvider()
perf = p._strategy_perf()
bd = perf.get('by_day', {})
total = 0.0
for k in sorted(bd.keys()):
    v = bd[k]
    pnl = v.get('pnl', 0) or 0
    total += pnl
    flag = ' [reset_conflict]' if v.get('reset_conflict') else ''
    print(f'  {k}: pnl={pnl}, trades={v.get("trades")}{flag}')
print(f'  -> summed (sanity): {total:.2f}')
print(f'  -> paper_state.realized_pnl: {perf.get("reconciliation", {}).get("cap_dropped_days") and "see below"}')
print()
recon = perf.get('reconciliation', {})
print(f'paper_realized_truth = {recon.get("paper_realized_pnl_truth_rs")}')
print(f'cap_dropped_days = {recon.get("cap_dropped_days")}')
print()
ps = p._paper_state()
print(f'paper_state.realized_pnl = {ps.get("realized_pnl")}')