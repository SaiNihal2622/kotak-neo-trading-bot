import sys
sys.path.insert(0, r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
from system.brain.bayesian_decision import _fetch_yfinance_empirical, decide

emp = _fetch_yfinance_empirical()
print(f'empirical keys: {list(emp.keys()) if emp else "empty"}')
if emp:
    ls = emp.get("long_signal") or {}
    ss = emp.get("short_signal") or {}
    print(f'long_signal: n={ls.get("n")} win={ls.get("win_rate")} sharpe={ls.get("sharpe")}')
    print(f'short_signal: n={ss.get("n")} win={ss.get("win_rate")} sharpe={ss.get("sharpe")}')
print(f'\ndecide: {decide()}')