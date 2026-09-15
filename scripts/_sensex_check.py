#!/usr/bin/env python
import json
import yfinance as yf

# SENSEX in decisions
with open('data_cache/quant_service_decisions.jsonl', encoding='utf-8') as f:
    lines = f.readlines()
sensex_mentions = [l for l in lines if 'SENSEX' in l]
print(f'SENSEX mentioned in {len(sensex_mentions)} of {len(lines)} decisions today')

# SENSEX spot today
t = yf.Ticker('^BSESN')
hist = t.history(period='1d', interval='5m')
if len(hist) > 0:
    o = hist['Open'].iloc[0]
    h = hist['High'].max()
    l = hist['Low'].min()
    p = hist['Close'].iloc[-1]
    pct = (p - o) / o * 100
    print(f'\nSENSEX today: open {o:.2f} high {h:.2f} low {l:.2f} last {p:.2f} ({pct:+.2f}%)')
    print(f'day range: {h-l:.2f} pts = {((h-l)/o*100):.2f}% of open')
    moves = hist['Close'].pct_change().abs() * 100
    print(f'max 5-min move: {moves.max():.3f}%')
else:
    print('no SENSEX data today')
