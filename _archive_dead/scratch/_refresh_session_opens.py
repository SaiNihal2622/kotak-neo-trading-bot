import json
from pathlib import Path
from datetime import datetime

# Pull current spots from just-refreshed option_chains.json
chains = json.load(open('data_cache/option_chains.json'))
spots = {sym: data['spot'] for sym, data in chains['chains'].items() if 'spot' in data and data['spot']}
print(f'Got {len(spots)} spots from option_chains.json')
nifty_spot = spots.get('NIFTY')
bnf_spot = spots.get('BANKNIFTY')
print(f'NIFTY={nifty_spot} BNF={bnf_spot}')

# Today's opens ARE today's first LTP; for pre-market we approximate from the just-fetched spot
today = datetime.now().strftime('%Y-%m-%d')
payload = {'date': today, 'opens': spots}
Path('data_cache/session_opens.json').write_text(json.dumps(payload, indent=2), encoding='utf-8')
print(f'Wrote session_opens.json: date={today} n={len(spots)}')

# Also refresh intraday_levels.json session_opens section
il_path = Path('data_cache/intraday_levels.json')
if il_path.exists():
    il = json.load(open(il_path))
    il['date'] = today
    il['session_opens'] = spots
    il['ts'] = datetime.now().isoformat()
    il_path.write_text(json.dumps(il, indent=2), encoding='utf-8')
    print(f'Also updated intraday_levels.json session_opens section')
