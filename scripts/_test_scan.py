#!/usr/bin/env python
"""Manually trigger a periodic LLM scan to test the 24/7 mode."""
import sys, json, time
from pathlib import Path
ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
sys.path.insert(0, str(ROOT / 'scripts'))
import importlib
import quant_service
importlib.reload(quant_service)

print('=== test 24/7 periodic scan ===')
print(f'  is_market_hours(): {quant_service.is_market_hours()}')
print(f'  now: {time.time()}')
print(f'  last_periodic_scan_ts: {quant_service.last_periodic_scan_ts}')
print(f'  diff: {time.time() - quant_service.last_periodic_scan_ts:.0f}s')
print(f'  threshold: 5400s')
print(f'  should fire: {(time.time() - quant_service.last_periodic_scan_ts) > 5400}')

# Try invoking the LLM
print()
print('=== try invoking LLM directly ===')
import os
for line in (ROOT / 'config' / 'credentials.env').read_text(encoding='utf-8').splitlines():
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, v = line.split('=', 1)
        if k.strip() not in os.environ:
            os.environ[k.strip()] = v.strip().strip('"').strip("'")

# Build minimal context
import json
gs = {}
try:
    with open(ROOT / 'data_cache' / 'global_state.json', encoding='utf-8') as f:
        gs = json.load(f)
except Exception as e:
    print(f'  global_state err: {e}')

context = {
    "liveness": {"snapshot": {"vix": 11.91, "open_positions": 0, "capital": 100000}},
    "paper": {"cash": 100000, "realized_pnl": 0, "positions": {}, "orders": []},
    "intraday": {},
    "chains_summary": {},
    "candles": {},
    "global_markets": gs,
    "alpha": {},
    "trigger": "test_24_7",
    "nse_status": "CLOSED",
}
print(f'  context keys: {list(context.keys())}')
print('  invoking LLM (this may take 5-10s)...')
try:
    decision = quant_service.invoke_llm_decision([{"type": "periodic_scan", "symbol": "ALL", "pct": 0, "price": 0, "trigger": "manual_test"}], context)
    print(f'  decision: type={decision.get("type")}')
    rat = decision.get("rationale", "")
    print(f'  rationale (first 200): {rat[:200]}')
except Exception as e:
    print(f'  err: {e}')
    import traceback
    traceback.print_exc()
