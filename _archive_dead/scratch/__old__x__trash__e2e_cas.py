"""End-to-end: simulate trending day + ADX=30, see if CAS fires."""
import os
import sys
import json
import random
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, '.')

# Setup tmpdir with synthetic candles_aggregate.json
tmpdir = tempfile.mkdtemp()
os.chdir(tmpdir)
Path('data_cache').mkdir(exist_ok=True)
Path('data_cache/candles_aggregate.json').write_text(
    json.dumps({'symbols': {'NIFTY': {'indicators': {'adx': 30}}}})
)

from scripts.strategy_library import select_strategy, STRATEGIES

# Trending day
random.seed(123)
varying = []
p = 22500
for i in range(40):
    delta = random.randint(-10, 25)
    p = p + delta
    varying.append(p)
print(f'Trending: +{varying[-1] - varying[0]} over 40 bars, session_pct={(varying[-1]-varying[0])/varying[0]*100:.2f}%')

context = {
    'spot': varying[-1],
    'vix': 14.0,
    'session_open': varying[0],
    'candles': [{'o': c, 'h': c+1, 'l': c-1, 'c': c, 'v': 1000} for c in varying],
    'now': datetime.now().replace(hour=11, minute=0, second=0, microsecond=0),
    'vwap': varying[-1],
}
strat = select_strategy(context, {})
print(f'\nSelection with ADX=30 + session_pct=+0.9%: {strat.name if strat else None}')
if strat:
    plan = STRATEGIES and __import__('scripts.strategy_library', fromlist=['generate_trade_plan']).generate_trade_plan(strat, context, capital=100000, vix=14.0)
    print(f'Plan structure: {plan["structure"]}')
    print(f'Plan legs: {plan["legs"]}')
    print(f'Plan target_pnl: Rs.{plan.get("target_pnl", 0):.0f}')
    print(f'Plan stop_pnl: Rs.{plan.get("stop_pnl", 0):.0f}')