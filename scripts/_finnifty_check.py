"""Look at FINNIFTY strikes."""
import json
ch = json.load(open('data_cache/option_chains.json'))
finnifty = ch['chains']['FINNIFTY']
print(f"ATM: {finnifty.get('atm_strike')}")
print(f"Spot: {finnifty['spot']}")
strikes = list(finnifty.get('strikes', {}).items())
print(f"Strike count: {len(strikes)}")
print("Strikes 20-30:")
for k, v in strikes[20:30]:
    s = v.get('strike')
    ot = v.get('opt_type')
    p = v.get('price')
    print(f"  key={k} strike={s} opt_type={ot} price={p}")
