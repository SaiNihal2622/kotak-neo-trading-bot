import json
d = json.load(open('data_cache/intraday_levels.json'))
print('ts:', d.get('ts'))
for sym in ('NIFTY', 'BANKNIFTY'):
    i = d.get('instruments', {}).get(sym, {})
    opn = i.get('open', 0)
    cur = i.get('current', 0)
    hi = i.get('day_high', 0)
    lo = i.get('day_low', 0)
    rng = ((cur - opn) / opn * 100) if opn else 0
    print(f'{sym}: open={opn} current={cur} high={hi} low={lo} range_pct={rng:.3f}% vwap={i.get("vwap")}')
