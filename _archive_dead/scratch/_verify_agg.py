import json
d = json.load(open('data_cache/candles_aggregate.json'))
print('ts:', d.get('ts'))
for sym in ('NIFTY', 'BANKNIFTY'):
    s = d.get('symbols', {}).get(sym, {})
    print(f'{sym}: ltp={s.get("ltp")} session_open={s.get("session_open")} session_pct={s.get("session_pct")} bars_1m_count={len(s.get("bars_1m_recent", []))}')
    if s.get('bars_1m_recent'):
        print(f'  last bar: {s["bars_1m_recent"][-1]}')
