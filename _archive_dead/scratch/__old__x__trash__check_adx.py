"""Verify ADX is now in candles_aggregate.json."""
import json
with open('data_cache/candles_aggregate.json', 'r', encoding='utf-8') as f:
    ca = json.load(f)
nifty = ca.get('symbols', {}).get('NIFTY', {})
inds = nifty.get('indicators', {})
adx = inds.get('adx')
rsi = inds.get('rsi_14')
trend = inds.get('ema_trend')
print(f"NIFTY ADX: {adx}")
print(f"NIFTY RSI-14: {rsi}")
print(f"NIFTY EMA trend: {trend}")
print(f"Has ADX: {'adx' in inds}")