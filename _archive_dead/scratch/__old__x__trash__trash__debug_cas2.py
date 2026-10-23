"""Debug script — see the actual candidates being created."""
import sys, os, tempfile, json
from pathlib import Path
sys.path.insert(0, '.')
from datetime import datetime
from scripts.strategy_library import STRATEGIES, compute_rsi, vol_targeted_size, generate_trade_plan

tmpdir = tempfile.mkdtemp()
os.chdir(tmpdir)
Path('data_cache').mkdir(exist_ok=True)
Path('data_cache/candles_aggregate.json').write_text(json.dumps({'symbols': {'NIFTY': {'indicators': {'adx': 30}}}}))

# Monkey-patch select_strategy to capture candidates
import scripts.strategy_library as sl

orig_select = sl.select_strategy

def patched_select(context, performance):
    spot = context.get('spot', 0)
    vix = context.get('vix', 15)
    session_open = context.get('session_open', spot)
    now = context.get('now') or datetime.now()
    vwap = context.get('vwap', spot)
    candles = context.get('candles', [])
    closes = [c.get('c', 0) for c in candles if c.get('c')]
    session_pct = (spot - session_open) / session_open * 100 if session_open else 0
    rsi14 = compute_rsi(closes[-15:])
    rsi2 = compute_rsi(closes[-5:])
    print(f"spot={spot} vix={vix} session_open={session_open}")
    print(f"session_pct={session_pct:.3f}% rsi14={rsi14}")
    print(f"dist_vwap={(spot-vwap)/vwap*100 if vwap else 0}")
    print(f"len(closes)={len(closes)}")

    # Manually replicate the candidates list
    candidates = []
    ic = STRATEGIES["iron_condor_nifty"]
    if vix < 15 and abs(session_pct) < 0.7 and ic.in_entry_window(now):
        print(f"  IC fires: vix<15?{vix<15} abs(sp)<0.7?{abs(session_pct)<0.7}")
        candidates.append((ic, 0.9, "low VIX + range-bound"))
    lp = STRATEGIES["long_put_nifty_bearish"]
    if session_pct < -0.5 and (rsi14 or 50) < 40 and lp.in_entry_window(now):
        print(f"  long_put fires: sp<-.5?{session_pct<-0.5} rsi<40?{(rsi14 or 50)<40}")
        candidates.append((lp, 0.7, "long put"))
    cs = STRATEGIES["nifty_cash_short"]
    adx_value = 0
    try:
        _ca = json.loads(Path("data_cache/candles_aggregate.json").read_text())
        _nifty_ca = (_ca.get("symbols") or {}).get("NIFTY") or {}
        adx_value = float(_nifty_ca.get("indicators", {}).get("adx") or 0)
    except Exception as e:
        print(f"  ADX load failed: {e}")
    print(f"  adx_value={adx_value}")
    if (adx_value > 25 and (rsi14 or 50) < 45
            and session_pct < -0.3 and cs.in_entry_window(now)):
        print(f"  cash_short fires: adx>25?{adx_value>25} rsi<45?{(rsi14 or 50)<45} sp<-.3?{session_pct<-0.3}")
        candidates.append((cs, 0.75, "cash_short"))
    print(f"Candidates: {[(c[0].name, c[1]) for c in candidates]}")
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates[0][0]

# Build downtrending context
spot = 22300
session_open = 22500
closes = [22500 - i * 5 for i in range(20)]
closes[-1] = 22300
candles = [{'o': c, 'h': c + 2, 'l': c - 2, 'c': c, 'v': 1000} for c in closes]
candles[-1]['c'] = spot
candles[-1]['h'] = spot
candles[-1]['l'] = spot
candles[-1]['o'] = spot

result = patched_select(
    {
        'spot': spot, 'vix': 13.0, 'session_open': session_open,
        'candles': candles,
        'now': datetime.now().replace(hour=11, minute=0, second=0, microsecond=0),
        'vwap': spot,
    },
    {}
)
print(f"\nFINAL: {result.name if result else None}")