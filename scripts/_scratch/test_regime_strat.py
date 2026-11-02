"""Smoke test new online_learner breakdowns."""
import sys
sys.path.insert(0, r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
from system.brain.online_learner import update, get_regime_strategy_stats

state = update()
print(f'global n={state["global"]["n"]}')
print(f'by_regime_strategy regimes: {list(state.get("by_regime_strategy", {}).keys())}')
print(f'by_strategy_side strategies: {list(state.get("by_strategy_side", {}).keys())}')
for regime in state.get('by_regime_strategy', {}):
    for strat, s in state['by_regime_strategy'][regime].items():
        print(f'  {regime} / {strat}: n={s["n"]} win={s.get("win_rate", 0)*100:.1f}% avg_pnl={s.get("avg_pnl", 0):.0f}')
print()
print('lookup test:')
print('  trending_up / nifty_cash_long:', get_regime_strategy_stats('trending_up', 'nifty_cash_long'))
print('  trending_up / nifty_swing_long:', get_regime_strategy_stats('trending_up', 'nifty_swing_long'))
print('  trending_up / never_run:', get_regime_strategy_stats('trending_up', 'never_run'))
print('  range_bound / nifty_iron_condor:', get_regime_strategy_stats('range_bound', 'nifty_iron_condor'))