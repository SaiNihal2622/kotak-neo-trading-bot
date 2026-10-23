"""Check market state for trade possibility."""
import json

with open('data_cache/intraday_levels.json', 'r', encoding='utf-8') as f:
    levels = json.load(f)
nifty = levels.get('instruments', {}).get('NIFTY', {})
session_open = nifty.get('open', 0)
current = nifty.get('current', nifty.get('ltp', 0))
vwap = nifty.get('vwap', 0)
session_pct = (current - session_open) / session_open * 100 if session_open else 0

with open('data_cache/candles_aggregate.json', 'r', encoding='utf-8') as f:
    ca = json.load(f)
inds = ca.get('symbols', {}).get('NIFTY', {}).get('indicators', {})

print(f"NIFTY session_open: {session_open}")
print(f"NIFTY current:      {current}")
print(f"NIFTY VWAP:         {vwap}")
print(f"NIFTY session_pct:  {session_pct:+.3f}%")
print(f"NIFTY ADX:          {inds.get('adx')}")
print(f"NIFTY RSI-14:       {inds.get('rsi_14')}")

# CAS would need ADX>25 + RSI>55 + session_pct>0.3 (long) or RSI<45 + session_pct<-0.3 (short)
adx = inds.get('adx', 0)
rsi = inds.get('rsi_14', 50)
cas_long = adx > 25 and rsi > 55 and session_pct > 0.3
cas_short = adx > 25 and rsi < 45 and session_pct < -0.3
print()
print(f"CAS long possible?  {cas_long}  (ADX>25={adx>25}, RSI>55={rsi>55}, session>0.3={session_pct>0.3})")
print(f"CAS short possible? {cas_short}  (ADX>25={adx>25}, RSI<45={rsi<45}, session<-0.3={session_pct<-0.3})")