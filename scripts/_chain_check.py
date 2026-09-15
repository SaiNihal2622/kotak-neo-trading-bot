"""Check all option chains."""
import json
ch = json.load(open('data_cache/option_chains.json'))
for sym, info in ch['chains'].items():
    print(f"{sym}: spot={info.get('spot')} atm={info.get('atm_strike')} n_strikes={len(info.get('strikes',{}))}")
