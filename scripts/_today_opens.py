#!/usr/bin/env python
"""Show all brain decisions with rationale today + current market state."""
import json
import yfinance as yf

# All brain decisions today
with open('data_cache/quant_service_decisions.jsonl', encoding='utf-8') as f:
    decisions = [json.loads(l) for l in f if l.startswith('{2026')]

print('=== TODAY\'S DECISIONS (with rationale) ===')
for d in decisions:
    if len(d.get('decision', {}).get('rationale', '')) < 50:
        continue
    ts = d.get('ts', '?')
    typ = d['decision'].get('type', '?')
    rat = d['decision'].get('rationale', '')
    scrub = ' [SCRUB]' if d['decision'].get('rationale_scrubbed') else ''
    print(f'\n  {ts} | {typ}{scrub}')
    print(f'    {rat[:300]}')

# Market state
print()
print('=== MARKET STATE ===')
t = yf.Ticker('^NSEI')
h = t.history(period='2d', interval='1d')
today = h.iloc[-1]
yest = h.iloc[-2] if len(h) > 1 else today
day_range = today['High'] - today['Low']
pct = day_range / yest['Close'] * 100
print(f'  NIFTY today: open={today["Open"]:.2f} high={today["High"]:.2f} low={today["Low"]:.2f} last={today["Close"]:.2f}')
print(f'  NIFTY prev close: {yest["Close"]:.2f}')
print(f'  Day range: {day_range:.2f} pts ({pct:.2f}% of prev close)')

v = yf.Ticker('^INDIAVIX')
vh = v.history(period='2d', interval='1d')
vix = vh['Close'].iloc[-1] if len(vh) else 0
print(f'  INDIA VIX: {vix:.2f}')

# 2 OPEN attempts today
opens = [d for d in decisions if d['decision'].get('type') == 'OPEN']
print()
print(f'=== OPEN ATTEMPTS: {len(opens)} ===')
for o in opens:
    print(f'  {o["ts"]} | {o["decision"].get("underlying")} {o["decision"].get("strategy")} | conf={o["decision"].get("confidence")}')
