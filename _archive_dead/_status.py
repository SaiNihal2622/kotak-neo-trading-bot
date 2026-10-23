import json
for sym in ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'SENSEX']:
    p = f'data_cache/option_chain_{sym}.json'
    with open(p) as f:
        d = json.load(f)
    if 'error' in d:
        print(f'{sym}: ERROR={d["error"]}')
        continue
    n_kotak = sum(1 for s in d.get('strikes', {}).values() if s.get('source') == 'kotak')
    print(f'{sym}: spot={d.get("spot")} source={d.get("source")} strikes={len(d.get("strikes",{}))} (kotak={n_kotak})')
