#!/usr/bin/env python
"""Manually call _periodic_scan to test."""
import sys, os, json, time
from pathlib import Path
ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
sys.path.insert(0, str(ROOT / 'scripts'))

# Load env
for line in (ROOT / 'config' / 'credentials.env').read_text(encoding='utf-8').splitlines():
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, v = line.split('=', 1)
        if k.strip() not in os.environ:
            os.environ[k.strip()] = v.strip().strip('"').strip("'")

import quant_service as qs

# Build context
gs = qs._safe_read_json(qs.DATA / "global_state.json", default={})
liveness = qs._safe_read_json(qs.DATA / "liveness.json", default={})
paper = qs._safe_read_json(qs.DATA / "paper_state.json", default={})

context = {
    "liveness": liveness,
    "paper": {k: paper.get(k) for k in ('cash', 'realized_pnl', 'positions', 'orders')},
    "intraday": {},
    "chains_summary": {},
    "candles": {},
    "global_markets": gs,
    "alpha": {},
    "trigger": "periodic_90min",
    "nse_status": "CLOSED",
}
print('=== calling _periodic_scan ===')
t0 = time.time()
try:
    decision = qs._periodic_scan(context=context)
    print(f'  completed in {time.time() - t0:.1f}s')
    print(f'  type: {decision.get("type")}')
    print(f'  rationale (first 200): {decision.get("rationale", "")[:200]}')
except Exception as e:
    import traceback
    print(f'  err after {time.time() - t0:.1f}s: {e}')
    traceback.print_exc()
