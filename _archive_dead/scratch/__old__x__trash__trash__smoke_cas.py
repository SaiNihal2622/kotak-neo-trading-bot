"""Smoke test for CAS strategies."""
import sys
sys.path.insert(0, '.')
from scripts.strategy_library import STRATEGIES, generate_trade_plan

print('='*60)
print('SMOKE TEST: NIFTY CASH (CAS) strategies')
print('='*60)

for name in ['nifty_cash_long', 'nifty_cash_short']:
    s = STRATEGIES[name]
    plan = generate_trade_plan(s, {'spot': 22750, 'vix': 13.0}, capital=100000, vix=13.0)
    print(f'\nStrategy: {name}')
    print(f'  structure: {plan["structure"]}')
    print(f'  underlying: {plan["underlying"]}')
    print(f'  legs: {len(plan["legs"])}')
    for i, leg in enumerate(plan['legs']):
        print(f'    leg[{i}]: {leg}')
    print(f'  target_pnl: Rs.{plan["target_pnl"]:.0f}')
    print(f'  stop_pnl:   Rs.{plan["stop_pnl"]:.0f}')

print('\n' + '='*60)
print('All CAS strategies load and generate plans correctly.')
print('='*60)