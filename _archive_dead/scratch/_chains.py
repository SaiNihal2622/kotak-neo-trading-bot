"""Check option chains."""
import json
with open('data_cache/option_chains.json', 'r', encoding='utf-8') as f:
    chains = json.load(f)
ts = chains.get('ts')
src = chains.get('source')
chains_dict = chains.get('chains', {})
print(f"ts: {ts}")
print(f"source: {src}")
print(f"chains dict: {len(chains_dict)} symbols")
print(f"symbols: {list(chains_dict.keys())[:10]}")
nifty = chains_dict.get('NIFTY', {})
print(f"NIFTY chain: {len(nifty)} strikes")
if nifty:
    first_strike = list(nifty.keys())[0]
    print(f"first strike: {first_strike}")
    print(f"first strike data: {nifty[first_strike]}")