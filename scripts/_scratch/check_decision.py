"""Diagnose why live_intel override isn't firing."""
import sys
sys.path.insert(0, r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
from system.brain.brain_daemon import BrainDaemon
from system.brain.live_intel import get_action_hint, fetch_intel
from system.brain.bayesian_decision import decide
from system.brain.strategy_selector import select_strategy
from system.brain.adaptive_sizer import size_for_strategy

# Stub signal_history for offline operation
import system.brain.signal_history as sh
sh.fetch_nifty_daily = lambda *a, **kw: []
def stub_empirical(*a, **kw):
    return {
        "long_signal": {"n": 24, "win_rate": 45.8, "sharpe": -1.51, "max_gain": 1.5, "max_loss": -1.0},
        "short_signal": {"n": 43, "win_rate": 39.5, "sharpe": 2.12, "max_gain": 2.0, "max_loss": -1.5},
    }
sh.empirical_signal_stats = stub_empirical

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

# Step 1: data-driven decision
dec = bd._data_driven_decision(state)
print(f'data-driven decision: action={dec["action"]}')
print(f'  rationale: {dec.get("rationale", "")[:200]}')

# Step 2: live_intel hint
hint = get_action_hint(22468, -0.33, -0.28)
print(f'\nlive_intel hint:')
for k, v in hint.items():
    print(f'  {k}: {v}')

# Step 3: bayesian
bayes = decide(segment='nse_cm')
print(f'\nbayes:')
print(f'  ev_short: {bayes["ev_short"]} win_short: {bayes["win_rate_short"]} n_short: {bayes["n_prior_short"]}')
print(f'  ev_long: {bayes["ev_long"]} win_long: {bayes["win_rate_long"]} n_long: {bayes["n_prior_long"]}')

# Step 4: check if live_intel override would fire
print(f'\nlive_intel override check:')
if hint['action_hint'] in ('SELL_RALLY', 'SELL_WEAK', 'BUY_DIP', 'BUY_BREAKOUT'):
    if hint['action_hint'].startswith('SELL'):
        ev = bayes.get('ev_short', 0)
        n_p = bayes.get('n_prior_short', 0)
    else:
        ev = bayes.get('ev_long', 0)
        n_p = bayes.get('n_prior_long', 0)
    cond1 = hint['confidence'] > 0.5
    cond2 = ev > -0.05
    cond3 = (n_p >= 30 or hint['confidence'] > 0.65)
    print(f'  confidence={hint["confidence"]} > 0.5: {cond1}')
    print(f'  ev={ev} > -0.05: {cond2}')
    print(f'  n_prior={n_p} >= 30 or conf>0.65: {cond3}')
    print(f'  WOULD FIRE: {cond1 and cond2 and cond3}')
else:
    print(f'  hint is HOLD/UNKNOWN, no override')

# Step 5: live intel details
intel = fetch_intel()
print(f'\nlive intel: bias={intel.get("consensus_bias")}')
print(f'  nearest_support: {intel.get("nearest_support")} (dist {intel.get("distance_to_support_pct")}%)')
print(f'  nearest_resistance: {intel.get("nearest_resistance")} (dist {intel.get("distance_to_resistance_pct")}%)')

# Step 6: try with higher confidence by adjusting session_pct (more bearish)
print('\n=== With more bearish session (-1.5%) ===')
state2 = dict(state)
state2['session_pct'] = -1.5
state2['dist_from_vwap'] = -0.50
hint2 = get_action_hint(22400, -1.5, -0.50)
print(f'hint: {hint2}')
intel2 = fetch_intel()
print(f'  nearest_support: {intel2.get("nearest_support")}')
print(f'  distance to support: {intel2.get("distance_to_support_pct")}%')
print(f'  consensus: {intel2.get("consensus_bias")}')