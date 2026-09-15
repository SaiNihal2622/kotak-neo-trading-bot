#!/usr/bin/env python
"""Compute missed profit on the two lost trades."""
import yfinance as yf
import math
from datetime import datetime, timedelta

# NIFTY current spot
t = yf.Ticker('^NSEI')
hist = t.history(period='2d', interval='1d')
spot_now = float(hist['Close'].iloc[-1])
print(f'NIFTY spot now: {spot_now:.2f}')
print()

# NIFTY option chain for nearest expiry (today 02-Sep-2026 is Wednesday, so weekly expiry is Thursday 03-Sep)
t = yf.Ticker('^NSEI')
exps = list(t.options or [])
print(f'Available NIFTY expiries: {exps[:5]}')
# Find nearest Thursday (03-Sep-2026)
target = '2026-09-03'
chosen = exps[0]
for e in exps:
    if e == target:
        chosen = e
        break
print(f'Using expiry: {chosen}')

oc = t.option_chain(chosen)
calls = oc.calls
puts = oc.puts
print(f'Got {len(calls)} call strikes, {len(puts)} put strikes')
print()

# Filter strikes around 23700-24000
relevant_strikes = [23700, 23800, 23900, 24000, 24100]
print(f'{"Strike":>8} {"Type":>5} {"LTP":>10} {"Intrinsic":>10} {"Extrinsic":>10} {"IV%":>7}')
for strike in relevant_strikes:
    row = puts[puts['strike'] == strike]
    if len(row):
        r = row.iloc[0]
        ltp = float(r['lastPrice'])
        intrinsic = max(0, spot_now - strike)
        extrinsic = max(0, ltp - intrinsic)
        iv = r.get('impliedVolatility', 0) * 100
        print(f'{strike:>8} {"PE":>5} {ltp:>10.2f} {intrinsic:>10.2f} {extrinsic:>10.2f} {iv:>7.1f}')

print()
print('=' * 70)
print('TRADE 1: 09:08 NIFTY bear_put_vertical (lost due to pre-open bug)')
print('  Signal: BUY 23900 PE + SELL 23700 PE, qty 75 each (1 lot)')
print('  Target: Rs.4,500 (premium) | Stop: Rs.1,500 | Max hold: 180 min')
print('  NIFTY at signal: ~24,000 | NIFTY now: {:.2f} ({:+.0f} pts)'.format(spot_now, spot_now - 24000))
print()
# At signal time (09:08), NIFTY was ~23980-24000, both puts were OTM with small premiums
# At expiry 03-Sep, max profit = 200 - premium = 200 - (~30 estimated)
# At current spot 23836:
#   23900 PE intrinsic = max(0, 23900 - 23836) = 64 -> OTM with some extrinsic
#   23700 PE intrinsic = max(0, 23700 - 23836) = 136 ITM
# So the spread is being closed with some intrinsic captured

# Get current LTPs
p23900 = float(puts[puts['strike'] == 23900].iloc[0]['lastPrice']) if len(puts[puts['strike'] == 23900]) else 0
p23700 = float(puts[puts['strike'] == 23700].iloc[0]['lastPrice']) if len(puts[puts['strike'] == 23700]) else 0
# At signal: NIFTY ~24000, 23900 PE was probably ~50-70 (ATM-ish), 23700 PE was probably ~10-15 (deep OTM)
# Estimate: paid ~60 debit for the spread
estimated_entry_debit = 60  # rough estimate of net premium paid
current_spread_value = p23900 - p23700  # what we'd get if we closed now (BUY leg - SELL leg)
profit_per_share = current_spread_value - estimated_entry_debit
total_profit = profit_per_share * 75
print(f'  Entry spread (estimated debit): ~Rs.{estimated_entry_debit} per share')
print(f'  Current spread (mark-to-market): Rs.{current_spread_value:.2f} per share')
print(f'  Profit per share: Rs.{profit_per_share:+.2f}')
print(f'  Total P&L (75 qty): Rs.{total_profit:+,.0f}')
print(f'  (Note: the bot would have used MARKET order, so real entry was likely worse than 60)')
print()

print('TRADE 2: 10:31 NIFTY long_put (lost due to UnboundLocalError on Order)')
print('  Signal: BUY 24000 PE, qty 75 (1 lot)')
print('  Target: Rs.120 (premium) | Stop: Rs.55 | Max hold: 180 min')
print('  NIFTY at signal: ~23,950-24,000 (already in selloff) | NIFTY now: {:.2f}'.format(spot_now))
print()
# At signal time, 24000 PE was about Rs.30-50 premium (OTM)
# At current spot 23836, 24000 PE is Rs.164 ITM, premium should be Rs.180-220
p24000 = float(puts[puts['strike'] == 24000].iloc[0]['lastPrice']) if len(puts[puts['strike'] == 24000]) else 0
# Estimate entry: NIFTY was around 23980 when signal hit, 24000 PE was probably Rs.40-60
estimated_entry_premium = 50
profit_per_share = p24000 - estimated_entry_premium
total_profit = profit_per_share * 75
print(f'  Entry premium (estimated): ~Rs.{estimated_entry_premium} per share')
print(f'  Current LTP: Rs.{p24000:.2f} per share (mark-to-market)')
print(f'  Profit per share: Rs.{profit_per_share:+.2f}')
print(f'  Total P&L (75 qty): Rs.{total_profit:+,.0f}')
print(f'  (Note: target was +120, would have hit target at NIFTY ~23,820, then probably scaled out)')
print()

print('=' * 70)
total = (current_spread_value - estimated_entry_debit) * 75 + (p24000 - estimated_entry_premium) * 75
print(f'COMBINED MISSED P&L (1 lot each, rough estimate): Rs.{total:+,.0f}')
print()
print('Caveats:')
print('  - Entry premium estimates are approximate (NIFTY was at 24000-23980 at signals)')
print('  - Real entries would have been market orders, so a few Rs/share worse')
print('  - These are mid-day MTM, not realized P&L (would have been closed at target/stop/EOD)')
print('  - Order was 1 lot = 75 qty (NIFTY lot size)')
