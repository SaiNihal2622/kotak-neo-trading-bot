"""Phase 8 smoke test (without yfinance noise)."""
import sys, json
sys.path.insert(0, r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')

# Stub out signal_history to avoid yfinance network failures
import system.brain.signal_history as sh
def _stub_fetch(*a, **kw): return []
def _stub_empirical(*a, **kw):
    return {
        "long_signal": {"n": 24, "win_rate": 45.8, "sharpe": -1.51, "max_gain": 1.5, "max_loss": -1.0},
        "short_signal": {"n": 43, "win_rate": 39.5, "sharpe": 2.12, "max_gain": 2.0, "max_loss": -1.5},
        "lookback_days": 246,
    }
def _stub_rv(*a, **kw): return 10.15
def _stub_vs(*a, **kw): return 1.18
sh.fetch_nifty_daily = _stub_fetch
sh.empirical_signal_stats = _stub_empirical
sh.realized_volatility = _stub_rv
sh.vol_scaling_factor = _stub_vs
sh.get_signal_context_for_prompt = lambda: ""

from system.brain.strategy_selector import select_strategy, get_selection_context_for_prompt
from system.brain.adaptive_sizer import (
    kelly_fraction, fractional_kelly, compute_position_size,
    size_for_strategy, get_sizer_context_for_prompt,
)
from system.brain.adaptive_exits import (
    compute_exits, exits_for_strategy, get_exits_context_for_prompt,
)

print("=== 1. Strategy selector (no data, bayesian fallback) ===")
state = {"regime": "trending_up", "adx": 30, "rsi": 65, "vix": 14}
sel = select_strategy(state)
print(f"  recommended: {sel['recommended']}")
print(f"  reason: {sel['reason']}")
print(f"  candidates:")
for c in sel["candidates"][:3]:
    print(f"    {c['strategy']:24s} score={c['score']:+.3f}  win={c.get('win_rate', 0)*100:.1f}%")

print("\n=== 2. Kelly math ===")
print(f"  60%/1.5%/1.0%: full_kelly={kelly_fraction(0.60, 1.5, 1.0):.3f} frac={fractional_kelly(0.60, 1.5, 1.0):.3f}")
print(f"  40% (no edge): full_kelly={kelly_fraction(0.40, 1.0, 1.0):.3f}")
print(f"  70%/2.0%/0.5% (great edge): full_kelly={kelly_fraction(0.70, 2.0, 0.5):.3f}")

print("\n=== 3. Position sizing ===")
s1 = compute_position_size(win_rate=0.60, avg_win_pct=1.5, avg_loss_pct=1.0, cash=100_000.0)
print(f"  Good edge: {s1['lots']} lots, {s1['qty']} shares, {s1['pct_of_capital']*100:.1f}% cap, full_k={s1['full_kelly']:.3f}")
s2 = compute_position_size(win_rate=0.40, avg_win_pct=1.0, avg_loss_pct=1.0, cash=100_000.0)
print(f"  No edge: {s2['lots']} lots (should be 0)")
s3 = compute_position_size(win_rate=0.70, avg_win_pct=2.0, avg_loss_pct=0.5, cash=100_000.0)
print(f"  Great edge: {s3['lots']} lots, {s3['qty']} shares, {s3['pct_of_capital']*100:.1f}% cap")

print("\n=== 4. Adaptive exits ===")
ex = compute_exits(avg_gain_rupees=1500, avg_loss_rupees=1000, realized_vol_pct=10.0)
print(f"  With data: target=+{ex['target_pct']:.2f}%, stop=-{ex['stop_pct']:.2f}%")
ex_d = compute_exits(avg_gain_rupees=0, avg_loss_rupees=0)
print(f"  Defaults: target=+{ex_d['target_pct']:.2f}%, stop=-{ex_d['stop_pct']:.2f}%")

print("\n=== 5. Prompt context blocks ===")
print("--- selector ---")
print(get_selection_context_for_prompt(state))
print("--- sizer ---")
print(get_sizer_context_for_prompt(state))
print("--- exits ---")
print(get_exits_context_for_prompt(state))

print("\n=== 6. brain_daemon._data_driven_decision (trending_up, no local data) ===")
from system.brain.brain_daemon import BrainDaemon
import system.brain.brain_daemon as bd_mod
bd_mod._days_to_expiry = lambda *a, **kw: 6  # not in blackout

bd = BrainDaemon.__new__(BrainDaemon)
test_state = {
    "regime": "trending_up",
    "adx": 30, "rsi": 65, "vix": 14,
    "session_pct": 0.5, "dist_from_vwap": 0.1,
    "vol_scaling": 1.2, "realized_vol_pct": 10.0,
    "cash": 100_000.0, "open_positions": [],
}
decision = bd._data_driven_decision(test_state)
print(f"  action: {decision['action']}")
print(f"  rationale: {decision.get('rationale', '')[:200]}")

print("\n=== PHASE 8 SMOKE PASSED ===")