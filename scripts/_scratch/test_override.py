"""Direct test of override conditions."""
import sys
sys.path.insert(0, r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
from system.brain.brain_daemon import BrainDaemon
from system.brain.live_intel import get_action_hint
from system.brain.bayesian_decision import decide

bd = BrainDaemon.__new__(BrainDaemon)
import system.brain.brain_daemon as bd_mod
bd_mod._days_to_expiry = lambda *a, **kw: 6

state = {
    'regime': 'trending_down',
    'adx': 30, 'rsi': 30, 'vix': 14,
    'session_pct': -0.33, 'dist_from_vwap': -0.28,
    'vol_scaling': 1.2, 'realized_vol_pct': 10.0,
    'cash': 100_000.0, 'open_positions': [],
    'nifty_spot': 22468,
}

# Test what _data_driven_decision returns directly
dec = bd._data_driven_decision(state)
print(f'_data_driven_decision: action={dec["action"]}')
print(f'  rationale: {dec.get("rationale", "")[:200]}')

# Test live_intel hint
hint = get_action_hint(22468, -0.33, -0.28)
print(f'\nlive_intel hint:')
print(f'  action_hint: {hint["action_hint"]}')
print(f'  confidence: {hint["confidence"]}')
print(f'  rationale: {hint["rationale"]}')

bayes = decide(segment='nse_cm')
print(f'\nbayes:')
print(f'  ev_short: {bayes["ev_short"]}')
print(f'  win_short: {bayes["win_rate_short"]}')
print(f'  n_prior_short: {bayes["n_prior_short"]}')
print(f'  sharpe_short: {bayes["sharpe_short"]}')

# Override conditions
cond1 = hint['confidence'] >= 0.4
cond2 = bayes['ev_short'] > -0.05
cond3 = (bayes['n_prior_short'] >= 30 or bayes['ev_short'] > 0)
print(f'\nOverride conditions:')
print(f'  conf={hint["confidence"]} >= 0.4: {cond1}')
print(f'  ev={bayes["ev_short"]} > -0.05: {cond2}')
print(f'  n={bayes["n_prior_short"]} >= 30 OR ev={bayes["ev_short"]} > 0: {cond3}')
print(f'\n>>> WOULD FIRE OVERRIDE: {cond1 and cond2 and cond3}')