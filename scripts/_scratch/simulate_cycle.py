"""Simulate a brain cycle with real production data."""
import sys, json, asyncio
sys.path.insert(0, r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')

# Read real intraday state
with open('data_cache/intraday_levels.json', encoding='utf-8') as f:
    intraday = json.load(f)

nifty = intraday['instruments']['NIFTY']
session_pct = float(nifty.get('session_pct', 0) or 0)
dist_vwap = float(nifty.get('dist_from_vwap', 0) or 0)
current = float(nifty.get('current', 0) or 0)

print(f"Real state: NIFTY={current} session_pct={session_pct} dist_vwap={dist_vwap}")

# Build state like brain_daemon._read_state would
state = {
    'ts': '2026-10-01T13:45:00+05:30',
    'open_positions': [],
    'vix': 13.64,
    'nifty_spot': current,
    'regime': 'trending_down',  # from session_pct -0.906
    'rsi': 50 + dist_vwap * 100,  # 50 + (-0.446)*100 = 5.4
    'adx': abs(session_pct) * 100,  # 90.6
    'macro_events': [],
    'session_pct': session_pct,
    'dist_from_vwap': dist_vwap,
    'realized_vol_pct': 10.15,
    'vol_scaling': 1.18,
    'cash': 100000.0,
}

# Get hint
from system.brain.live_intel import get_action_hint
hint = get_action_hint(current, session_pct, dist_vwap)
print(f"\nlive_intel hint: action_hint={hint['action_hint']} confidence={hint['confidence']}")
print(f"  rationale: {hint['rationale']}")

# Get bayes
from system.brain.bayesian_decision import decide
bayes = decide(segment='nse_cm')
print(f"\nbayes: ev_short={bayes['ev_short']} win={bayes['win_rate_short']} n={bayes['n_prior_short']}")

# Override conditions
ev = bayes['ev_short']
n_p = bayes['n_prior_short']
cond1 = hint['confidence'] >= 0.4
cond2 = ev > -0.05
cond3 = (n_p >= 30 or ev > 0)
print(f"\nOverride:")
print(f"  conf={hint['confidence']} >= 0.4: {cond1}")
print(f"  ev={ev} > -0.05: {cond2}")
print(f"  n={n_p} >= 30 or ev>0: {cond3}")
print(f"  WOULD FIRE: {cond1 and cond2 and cond3}")

if cond1 and cond2 and cond3:
    print("\n=== SIMULATING OVERRIDE FIRE ===")
    from system.brain.strategy_selector import select_strategy
    from system.brain.adaptive_sizer import size_for_strategy
    from system.brain.adaptive_exits import exits_for_strategy

    synth_state = dict(state)
    synth_state['regime'] = 'trending_down'
    synth_state['adx'] = max(state['adx'], 25)
    synth_state['rsi'] = min(state['rsi'], 45)

    sel = select_strategy(synth_state)
    print(f"\nselector: recommended={sel.get('recommended')} side={sel.get('side')} segment={sel.get('segment')}")

    if sel['recommended'] == 'hold':
        fallback = 'nifty_cash_short'
        sel = {'recommended': fallback, 'side': 'SELL', 'segment': 'nse_cm'}
        print(f"  fallback to {fallback}")

    sizing = size_for_strategy(
        'trending_down', sel['recommended'],
        realized_vol_pct=10.15, cash=100000.0,
    )
    print(f"\nsizing: lots={sizing['lots']} qty={sizing['qty']}")

    if sizing['lots'] == 0:
        sizing['lots'] = 1
        sizing['qty'] = 75
        print(f"  override: lots=1 qty=75")

    ex = exits_for_strategy(
        'trending_down', sel['recommended'],
        realized_vol_pct=10.15, is_swing='swing' in sel['recommended'],
    )
    print(f"\nexits: target=+{ex['target_pct']}% stop=-{ex['stop_pct']}%")

    decision = {
        'action': 'OPEN',
        'rationale': f"[LIVE-INTEL OVERRIDE] {hint['rationale']}",
        'strategy': sel['recommended'],
        'underlying': 'NIFTY',
        'legs': [{'side': 'SELL', 'qty': sizing['qty'], 'order_type': 'MARKET', 'segment': 'nse_cm'}],
        'target': ex['target_pct'] / 100,
        'stop': ex['stop_pct'] / 100,
    }
    print(f"\nFINAL DECISION:")
    print(json.dumps(decision, indent=2))