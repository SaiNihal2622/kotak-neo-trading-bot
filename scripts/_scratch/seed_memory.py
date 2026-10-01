"""Seed memory MCP with representative trades."""
import sys
sys.path.insert(0, r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
from system.common.memory_helper import remember_trade_outcome

seed_trades = [
    ('nifty_cash_short', 'SELL', 'trending_down', 1500.0, 1.5, True),
    ('nifty_cash_short', 'SELL', 'trending_down', -800.0, -0.8, False),
    ('nifty_cash_short', 'SELL', 'trending_down', 2000.0, 2.0, True),
    ('nifty_swing_long', 'BUY', 'trending_up', 3500.0, 3.5, True),
    ('nifty_swing_long', 'BUY', 'trending_up', -1500.0, -1.5, False),
    ('nifty_long_call', 'BUY', 'mild_up', 600.0, 0.6, True),
    ('nifty_long_call', 'BUY', 'range_bound', -2000.0, -2.0, False),
    ('nifty_iron_condor', 'SELL', 'range_bound', 1200.0, 1.2, True),
    ('nifty_iron_condor', 'SELL', 'range_bound', 1500.0, 1.5, True),
    ('nifty_long_put', 'BUY', 'trending_down', 800.0, 0.8, True),
]

ok_count = 0
for t in seed_trades:
    strategy, side, regime, pnl_r, pnl_p, win = t
    ok = remember_trade_outcome(strategy, side, regime, pnl_r, pnl_p, win,
                                  nifty_spot=22468, vix=14.0, adx=30.0)
    print(f'  {strategy} {side} {regime}: {"ok" if ok else "FAIL"}')
    if ok:
        ok_count += 1

print(f'\nSeeded {ok_count}/{len(seed_trades)} trades to memory MCP')

# Now recall
print('\n=== Recall: trending_down ===')
from system.common.memory_helper import get_memory_context_for_prompt
print(get_memory_context_for_prompt('trending_down'))

print('\n=== Recall: range_bound ===')
print(get_memory_context_for_prompt('range_bound'))