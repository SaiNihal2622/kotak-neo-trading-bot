"""Quick validation backtest of the strategy library on 30 days of NIFTY data."""
import sys
import json
import csv
from pathlib import Path
from datetime import datetime, time as dtime

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

from scripts.strategy_library import (
    STRATEGIES, select_strategy, generate_trade_plan,
    compute_rsi, compute_rsi2, distance_from_vwap, vol_targeted_size,
    StrategyResult,
)

# Read 1m candle data for NIFTY
candles_path = ROOT / "data_cache" / "candles" / "NIFTY_1m.jsonl"
candles = []
if candles_path.exists():
    for line in candles_path.read_text(encoding="utf-8").strip().split("\n")[-2000:]:
        try:
            candles.append(json.loads(line))
        except Exception:
            continue

print(f"Loaded {len(candles)} candles")
if candles:
    print(f"First: {candles[0].get('ts')}")
    print(f"Last:  {candles[-1].get('ts')}")

# Group by day
days = {}
for c in candles:
    ts = c.get("ts", "")
    day = ts[:10] if ts else "?"
    days.setdefault(day, []).append(c)

print(f"Days: {len(days)}")

# Run strategy selector on each day
n_selected = 0
selections = []
for day, day_candles in sorted(days.items()):
    if len(day_candles) < 30:
        continue
    session_open = day_candles[0].get("o", 0)
    closes = [c.get("c", 0) for c in day_candles]
    spot = day_candles[-1].get("c", 0)
    vwap = sum(c.get("c", 0) * c.get("v", 1) for c in day_candles) / max(1, sum(c.get("v", 1) for c in day_candles))
    rsi14 = compute_rsi(closes[-15:]) if len(closes) >= 15 else None
    rsi2 = compute_rsi2(closes[-5:]) if len(closes) >= 5 else None
    context = {
        "spot": spot, "vix": 13.5, "session_open": session_open,
        "candles": day_candles, "now": datetime.fromisoformat(day + "T12:00:00"),
        "vwap": vwap,
    }
    strategy = select_strategy(context, {})
    if strategy:
        n_selected += 1
        session_pct = (spot - session_open) / session_open * 100 if session_open else 0
        selections.append({
            "day": day,
            "strategy": strategy.name,
            "session_pct": session_pct,
            "rsi14": rsi14,
            "rsi2": rsi2,
            "dist_vwap": distance_from_vwap(spot, vwap),
        })

print(f"\nStrategy selected on {n_selected}/{len(days)} days")
print("\nSelections:")
for s in selections:
    print(f"  {s['day']}: {s['strategy']:30s} session_pct={s['session_pct']:+.2f}%  RSI14={s['rsi14']}  RSI2={s['rsi2']}  vwap={s['dist_vwap']:+.2f}%")
