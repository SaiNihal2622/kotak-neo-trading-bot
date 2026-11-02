"""Debug Bayesian merge."""
import sys
sys.path.insert(0, r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
from system.brain.bayesian_decision import (
    _fetch_yfinance_empirical, _fetch_local_outcomes,
    bayesian_update, decide,
)

emp = _fetch_yfinance_empirical()
local = _fetch_local_outcomes()

print("=== yfinance prior ===")
print(f"  long_signal: n={emp['long_signal']['n']} win={emp['long_signal']['win_rate']}")
print(f"  short_signal: n={emp['short_signal']['n']} win={emp['short_signal']['win_rate']}")

print("\n=== local outcomes ===")
print(f"  long: {local['long']}")
print(f"  short: {local['short']}")

print("\n=== bayesian_update with these inputs ===")
prior_long = {
    "win_rate": emp['long_signal']['win_rate'],
    "avg_gain": 1.0,
    "avg_loss": -1.0,
    "n": emp['long_signal']['n'],
    "sharpe": 0,
}
like_long = {
    "win_rate": local['long']['win_rate'],
    "avg_gain": 1.0,
    "avg_loss": -1.0,
    "n": local['long']['n'],
    "sharpe": 0,
}
merged = bayesian_update(prior_long, like_long)
print(f"  merged: {merged}")

print("\n=== decide() ===")
d = decide()
print(f"  n_prior_long={d['n_prior_long']} n_prior_short={d['n_prior_short']}")
print(f"  win_rate_long={d['win_rate_long']} win_rate_short={d['win_rate_short']}")
print(f"  ev_long={d['ev_long']} ev_short={d['ev_short']}")