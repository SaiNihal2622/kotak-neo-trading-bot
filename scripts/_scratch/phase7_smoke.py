"""Phase 7 smoke test — verify all 3 new modules import + produce sensible output."""
import sys
sys.path.insert(0, r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')

from system.brain.bayesian_decision import (
    get_decision_context_for_prompt, decide,
)
from system.brain.online_learner import (
    update, get_local_likelihood_for_bayesian, get_lessons_for_prompt,
)
from system.brain.regime_detector import (
    detect_shift, get_regime_shift_context,
)

print("=== 1. Bayesian EV decision ===")
d = decide()
print(f"  recommended={d['recommended']}")
print(f"  ev_long={d['ev_long']:+.4f}% ev_short={d['ev_short']:+.4f}%")
print(f"  win_long={d['win_rate_long']:.3f} win_short={d['win_rate_short']:.3f}")
print(f"  n_prior_long={d['n_prior_long']} n_prior_short={d['n_prior_short']}")
print(f"  sharpe_long={d['sharpe_long']} sharpe_short={d['sharpe_short']}")
print(f"  transaction_cost={d['transaction_cost_pct']*100:.1f}%")

print("\n=== 2. Online learner ===")
state = update()
print(f"  global: n={state['global']['n']} win={state['global'].get('win_rate', 0)*100:.1f}% "
      f"sharpe_est={state['global'].get('sharpe_estimate', 0)}")
print(f"  by_side: BUY n={state['by_side']['BUY']['n']} "
      f"win={state['by_side']['BUY'].get('win_rate', 0)*100:.1f}% "
      f"SELL n={state['by_side']['SELL']['n']} "
      f"win={state['by_side']['SELL'].get('win_rate', 0)*100:.1f}%")

print("\n=== 3. Local likelihood from learner ===")
long_like = get_local_likelihood_for_bayesian("BUY")
short_like = get_local_likelihood_for_bayesian("SELL")
print(f"  BUY: {long_like}")
print(f"  SELL: {short_like}")

print("\n=== 4. Regime shift detection ===")
shift = detect_shift({
    "regime": "trending_up", "session_pct": 0.5, "vix": 22.0,
    "adx": 35.0, "rsi": 65.0, "nifty_spot": 25000.0,
})
print(f"  shifted={shift['shifted']}")
print(f"  stability={shift['stability']}")
print(f"  reasons={shift['reasons']}")
print(f"  history_n={shift['history_n']}")

print("\n=== 5. Prompt context blocks ===")
bayes_ctx = get_decision_context_for_prompt()
print(f"  bayes_ctx length: {len(bayes_ctx)} chars")
if bayes_ctx:
    print(f"  bayes preview: {bayes_ctx[:300]}")

lessons_ctx = get_lessons_for_prompt()
print(f"  lessons_ctx length: {len(lessons_ctx)} chars")

regime_ctx = get_regime_shift_context()
print(f"  regime_ctx length: {len(regime_ctx)} chars")
if regime_ctx:
    print(f"  regime preview: {regime_ctx[:300]}")

print("\n=== SMOKE PASSED ===")