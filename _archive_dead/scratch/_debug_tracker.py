import sys
sys.path.insert(0, '.')
sys.path.insert(0, 'scripts')

# Force reload to ensure no caching
import importlib
import live_go_tracker
importlib.reload(live_go_tracker)

truth = live_go_tracker._paper_state_truth()
print('truth =', truth)

daily_pnl = live_go_tracker._daily_pnl_from_strategy_perf()
print('daily_pnl sum =', sum(daily_pnl.values()))

baseline = 100000
if truth:
    cumulative_pnl = truth["realized_pnl_rs"]
    cumulative_pct = truth["cumulative_return_pct"]
    print(f'cumulative_pnl = {cumulative_pnl}, cumulative_pct = {cumulative_pct}')

# Now run main()
print('\n--- main() ---')
live_go_tracker.main()