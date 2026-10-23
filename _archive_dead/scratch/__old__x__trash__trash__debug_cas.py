"""Debug script to find why cash_short test fails."""
import sys, os, tempfile, json
from pathlib import Path
sys.path.insert(0, '.')
from datetime import datetime
from scripts.strategy_library import STRATEGIES

tmpdir = tempfile.mkdtemp()
os.chdir(tmpdir)
Path('data_cache').mkdir(exist_ok=True)
Path('data_cache/candles_aggregate.json').write_text(json.dumps({'symbols': {'NIFTY': {'indicators': {'adx': 30}}}}))

import scripts.strategy_library as sl

orig_select = sl.select_strategy

def patched(context, performance):
    spot = context.get('spot', 0)
    vix = context.get('vix', 15)
    session_open = context.get('session_open', spot)
    now = context.get('now') or datetime.now()
    vwap = context.get('vwap', spot)
    candles = context.get('candles', [])
    closes = [c.get('c', 0) for c in candles if c.get('c')]
    lp_strat = STRATEGIES["long_put_nifty_bearish"]
    cs_strat = STRATEGIES["nifty_cash_short"]
    print(f"DEBUG: spot={spot} vix={vix} session_open={session_open}")
    print(f"DEBUG: vwap={vwap} len(closes)={len(closes)}")
    print(f"DEBUG: now={now} hour={now.hour} min={now.minute}")
    print(f"DEBUG: long_put entry_window: {lp_strat.in_entry_window(now)}")
    print(f"DEBUG: long_put start={lp_strat.entry_window_start} end={lp_strat.entry_window_end}")
    print(f"DEBUG: cash_short entry_window: {cs_strat.in_entry_window(now)}")
    print(f"DEBUG: cash_short start={cs_strat.entry_window_start} end={cs_strat.entry_window_end}")
    return orig_select(context, performance)

# Build downtrending context: spot=22300, session_open=22500 → -0.889%
spot = 22300
session_open = 22500
closes = [22500 - i * 5 for i in range(20)]
closes[-1] = 22300
candles = [{'o': c, 'h': c + 2, 'l': c - 2, 'c': c, 'v': 1000} for c in closes]
candles[-1]['c'] = spot
candles[-1]['h'] = spot
candles[-1]['l'] = spot
candles[-1]['o'] = spot

result = patched(
    {
        'spot': spot, 'vix': 13.0, 'session_open': session_open,
        'candles': candles,
        'now': datetime.now().replace(hour=11, minute=0, second=0, microsecond=0),
        'vwap': spot,
    },
    {}
)
print(f"\nFINAL RESULT: {result.name if result else None}")