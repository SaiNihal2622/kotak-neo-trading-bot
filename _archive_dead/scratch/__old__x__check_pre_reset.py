import json
b = json.load(open('data_cache/paper_state_pre_reset_20260920_182656.json'))
print('pre_reset_20260920_182656 (latest pre-restore snapshot):')
print(f'  cash = Rs.{b["cash"]:,.2f}')
print(f'  realized_pnl = Rs.{b["realized_pnl"]:+,.2f}')
print(f'  positions_count = {len(b.get("positions", {}))}')