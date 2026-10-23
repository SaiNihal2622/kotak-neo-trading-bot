"""Trace why conditions don't fire."""
import sys, os, tempfile, json
from pathlib import Path
sys.path.insert(0, '.')
from datetime import datetime
from scripts.strategy_library import STRATEGIES, compute_rsi

tmpdir = tempfile.mkdtemp()
os.chdir(tmpdir)
Path('data_cache').mkdir(exist_ok=True)
Path('data_cache/candles_aggregate.json').write_text(json.dumps({'symbols': {'NIFTY': {'indicators': {'adx': 30}}}}))

spot = 22300
session_open = 22500
closes = [22500 - i * 5 for i in range(20)]
closes[-1] = 22300
rsi14 = compute_rsi(closes[-15:])
print(f"rsi14={rsi14} type={type(rsi14).__name__}")

now = datetime.now().replace(hour=11, minute=0, second=0, microsecond=0)
lp = STRATEGIES["long_put_nifty_bearish"]
cs = STRATEGIES["nifty_cash_short"]

print(f"long_put.in_entry_window(now) = {lp.in_entry_window(now)}")
print(f"long_put.entry_window_start = {lp.entry_window_start}")
print(f"long_put.entry_window_end = {lp.entry_window_end}")

print(f"cash_short.in_entry_window(now) = {cs.in_entry_window(now)}")
print(f"cash_short.entry_window_start = {cs.entry_window_start}")
print(f"cash_short.entry_window_end = {cs.entry_window_end}")

session_pct = (spot - session_open) / session_open * 100
print(f"session_pct = {session_pct:.3f}")
print(f"session_pct < -0.5: {session_pct < -0.5}")
print(f"(rsi14 or 50) < 40: {(rsi14 or 50) < 40}")

print(f"\nLP full condition: session_pct<-0.5 AND rsi<40 AND in_entry_window")
print(f"  = {session_pct < -0.5} AND {(rsi14 or 50) < 40} AND {lp.in_entry_window(now)}")
print(f"  = {(session_pct < -0.5) and ((rsi14 or 50) < 40) and lp.in_entry_window(now)}")

print(f"\nCS full condition: adx>25 AND rsi<45 AND sp<-.3 AND in_window")
print(f"  = {30 > 25} AND {(rsi14 or 50) < 45} AND {session_pct < -0.3} AND {cs.in_entry_window(now)}")
print(f"  = {(30 > 25) and ((rsi14 or 50) < 45) and (session_pct < -0.3) and cs.in_entry_window(now)}")