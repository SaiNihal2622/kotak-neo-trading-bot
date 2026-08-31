"""Live re-evaluation of mavis_trades.json — bypasses pre-market snapshot logic.

Runs the same condition checks as mavis_premarket.py but uses LIVE data, not
the 8:35 snapshot. Updates mavis_trades.json with the current decision.

Called by:
- Manual user request (whenever the user wants a fresh check)
- kotak-trader-desk cron (TBD — should be added)
- kotak-mavis-intraday-refresh-1100/1330 crons (TBD — should be added)
"""
import json
import datetime
import yfinance
import os

DCACHE = r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache'
PLAN_PATH = os.path.join(DCACHE, 'mavis_trades.json')

now = datetime.datetime.now().astimezone()
print(f'[{now.isoformat()}] LIVE re-evaluation of entry conditions')

# Get live values
def _last(sym, interval='5m'):
    try:
        df = yfinance.Ticker(sym).history(period='1d', interval=interval)
        if df is None or df.empty:
            return 0.0
        closes = df['Close'].dropna()
        if closes.empty:
            return 0.0
        return float(closes.iloc[-1])
    except Exception:
        return 0.0

nifty = _last('^NSEI')
bnf = _last('^NSEBANK')
vix = _last('^INDIAVIX')

# US futures, vs previous day close
us_pct = {}
us_futures = {}
for sym, key in [('ES=F', 'spx'), ('NQ=F', 'nasdaq'), ('YM=F', 'dow')]:
    try:
        df = yfinance.Ticker(sym).history(period='5d', interval='1d')
        if df is None or df.empty or len(df) < 2:
            us_pct[key] = 0.0
            continue
        last = float(df['Close'].iloc[-1])
        prev = float(df['Close'].iloc[-2])
        us_pct[key] = (last - prev) / prev * 100
        us_futures[key] = last
    except Exception:
        us_pct[key] = 0.0

max_us = max(us_pct.values(), key=abs) if us_pct else 0.0

print(f'NIFTY {nifty:.2f} | BNF {bnf:.2f} | VIX {vix:.2f}')
print(f'US: spx={us_pct.get("spx", 0):+.2f}% nasdaq={us_pct.get("nasdaq", 0):+.2f}% dow={us_pct.get("dow", 0):+.2f}% max_abs={max_us:+.2f}%')

# Conditions
in_range = 24000 <= nifty <= 24500
us_calm = abs(max_us) < 0.4
vix_ok = 8 < vix < 12
print(f'IN RANGE: {in_range} | US CALM (<0.4%): {us_calm} | VIX OK (8-12): {vix_ok}')

if in_range and us_calm and vix_ok:
    action = 'EXECUTE_PLAN'
    reason = (
        f'LIVE re-eval {now.strftime("%H:%M IST")}: NIFTY {nifty:.0f} in 24k-24.5k, '
        f'US max {max_us:+.2f}% (calm), VIX {vix:.2f} (cheap). '
        f'Conditions clear, plan stands.'
    )
else:
    action = 'BLOCK'
    failed = []
    if not in_range:
        failed.append(f'NIFTY {nifty:.0f} outside 24k-24.5k')
    if not us_calm:
        failed.append(f'US {max_us:+.2f}% > 0.4% threshold')
    if not vix_ok:
        failed.append(f'VIX {vix:.2f} outside 8-12')
    reason = f'LIVE re-eval {now.strftime("%H:%M IST")}: BLOCK because {"; ".join(failed)}'

print(f'NEW DECISION: {action}')
print(f'REASON: {reason}')

# Update mavis_trades.json
if not os.path.exists(PLAN_PATH):
    print(f'ERR: {PLAN_PATH} not found', file=__import__('sys').stderr)
    raise SystemExit(1)

with open(PLAN_PATH, 'r', encoding='utf-8') as f:
    plan = json.load(f)

plan['valid_for_date'] = now.strftime('%Y-%m-%d')
plan['valid_for_session'] = f"{now.strftime('%a %d-%b-%Y')} NSE regular session"
plan['last_refresh_at'] = now.isoformat()
plan['last_decision_at'] = now.isoformat()
plan['mavis_decision']['action'] = action
plan['mavis_decision']['reason_short'] = reason
plan['mavis_decision']['refreshed_via'] = 'live_reeval'
plan['mavis_decision']['refreshed_at'] = now.isoformat()

research = plan.get('research_at_generation', {})
research['nifty_spot'] = round(nifty, 2)
research['banknifty_spot'] = round(bnf, 2)
research['india_vix'] = round(vix, 2)
research['us_futures_overnight'] = ', '.join(f'{k}={v:+.2f}%' for k, v in us_pct.items())
research['refreshed_at'] = now.isoformat()
plan['research_at_generation'] = research

premarket_check = plan.get('premarket_check', {})
premarket_check['spot_in_range'] = in_range
premarket_check['us_calm'] = us_calm
premarket_check['vix_ok'] = vix_ok
plan['premarket_check'] = premarket_check

with open(PLAN_PATH, 'w', encoding='utf-8') as f:
    json.dump(plan, f, indent=2, ensure_ascii=False)

print(f'WROTE {PLAN_PATH} with action={action}')
print(f'Bot will pick up the new plan on its next scan tick (~30s)')
