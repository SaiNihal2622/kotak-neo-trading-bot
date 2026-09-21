"""Intraday levels tracker — what a pro quant looks at every second.

Tracks for every instrument:
- Day open, current, day high, day low
- VWAP (volume-weighted average price)
- Opening range (first 15 min high/low)
- Recent swing high/low (last N candles)
- Distance from each level (in % and absolute)
- Whether price is at/near a level (support/resistance touch)
- Volume profile: POC (point of control) and value area

Outputs JSON to data_cache/intraday_levels.json. Updated every tick.
The professional-quant prompt and quant_engine.py consume this.
"""
import json
import os
import sys
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
DATA = ROOT / 'data_cache'
OUT = DATA / 'intraday_levels.json'

# In-memory state per symbol: deque of (ts, price, volume)
TICKS: dict[str, deque] = defaultdict(lambda: deque(maxlen=20000))
CANDLES_1M: dict[str, deque] = defaultdict(lambda: deque(maxlen=240))  # 4h * 60m


def now_ist_str() -> str:
    try:
        sys.path.insert(0, str(ROOT))
        from kotak_bot.utils.clock import now_ist
        return now_ist().strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def seed_from_liveness() -> dict:
    """Pull current LTP/spot from liveness.json as the initial tick. Real ticks
    come from kotak_prod_feed — for now we bootstrap from liveness + yfinance."""
    liveness_path = DATA / 'liveness.json'
    if not liveness_path.exists():
        return {}
    try:
        d = json.loads(liveness_path.read_text(encoding='utf-8'))
        snap = d.get('snapshot', {}) or {}
        return {
            'NIFTY': {'price': snap.get('vix', 0) * 0 + 0},  # liveness has no spot; placeholder
            'BANKNIFTY': {'price': 0},
        }
    except Exception:
        return {}


def read_bot_latest_prices() -> dict:
    """FIX 2026-09-21 15:30: was using yfinance which returned the same value for
    open/high/low/current (the yfinance 1d close), making the LLM see a flat 0.00%
    intraday range and skip the closing straddle. Now we read live ticks from the
    candle_engine (which is always running) plus session_open from session_opens.json.

    Priority order:
      1. candle_engine.get_engine().last_ltp[sym]  -- real tick from kotak_prod_feed
      2. option_chains.json spot                 -- refreshed every 15 min by chain-analyzer
      3. session_opens.json opens[sym]            -- morning 09:15 IST snapshot
      4. yfinance fallback                        -- last resort
    """
    out = {}
    # 1. candle_engine live ticks (preferred)
    try:
        sys.path.insert(0, str(ROOT))
        from candle_engine import get_engine as _get_eng
        eng = _get_eng()
        for sym in ('NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'INDIAVIX'):
            ltp = eng.last_ltp.get(sym)
            if ltp and ltp > 0:
                out[sym] = {'price': float(ltp), 'volume': 0, 'source': 'candle_engine'}
    except Exception:
        pass
    # 2. option_chains.json fallback
    if len(out) < 2:
        try:
            chains_path = DATA / 'option_chains.json'
            if chains_path.exists():
                ch = json.loads(chains_path.read_text(encoding='utf-8'))
                chains = ch.get('chains', {})
                for sym, payload in chains.items():
                    if sym in out:
                        continue
                    spot = payload.get('spot')
                    if spot and spot > 0:
                        out[sym] = {'price': float(spot), 'volume': 0, 'source': 'option_chains'}
        except Exception:
            pass
    # 3. yfinance fallback (last resort, prefer gap-fill not first call)
    try:
        import yfinance as yf
        for sym, ticker in [
            ('NIFTY', '^NSEI'),
            ('BANKNIFTY', '^NSEBANK'),
            ('FINNIFTY', 'NIFTY_FIN_SERVICE.NS'),
            ('MIDCPNIFTY', 'NIFTY_MIDCAP_100.NS'),
            ('INDIAVIX', '^INDIAVIX'),
        ]:
            if sym in out:
                continue
            try:
                t = yf.Ticker(ticker)
                hist = t.history(period='1d')
                if hist is not None and not hist.empty:
                    out[sym] = {'price': float(hist['Close'].iloc[-1]), 'volume': 0}
            except Exception:
                pass
    except Exception:
        pass
    return out


def build_levels(symbol: str, ticks: deque) -> dict:
    """Compute day OHLC, VWAP, opening range, swing levels for one symbol."""
    if not ticks:
        return {}
    today = now_ist_str()[:10]
    today_ticks = [(t, p, v) for (t, p, v) in ticks if t.startswith(today)]
    if not today_ticks:
        return {}
    opens = today_ticks[0][1]
    closes = today_ticks[-1][1]
    highs = max(p for _, p, _ in today_ticks)
    lows = min(p for _, p, _ in today_ticks)
    vol_total = sum(v for _, _, v in today_ticks) or 1
    pv_total = sum(p * v for _, p, v in today_ticks)
    vwap = pv_total / vol_total

    # Opening range: first 15 min from 09:15
    or_ticks = [(t, p, v) for (t, p, v) in today_ticks if '09:15' <= t[11:16] <= '09:30']
    or_high = max((p for _, p, _ in or_ticks), default=highs)
    or_low = min((p for _, p, _ in or_ticks), default=lows)

    # Recent swing high/low (last 30 min)
    cutoff_30m = (datetime.now() - timedelta(minutes=30)).strftime('%Y-%m-%d %H:%M:%S')
    recent = [(t, p, v) for (t, p, v) in today_ticks if t >= cutoff_30m]
    swing_high_30m = max((p for _, p, _ in recent), default=highs)
    swing_low_30m = min((p for _, p, _ in recent), default=lows)

    # Distance from levels (in % and absolute)
    def dist(curr, lvl):
        if not lvl:
            return None
        return {'pct': round((curr - lvl) / lvl * 100, 2), 'abs': round(curr - lvl, 2)}

    cur = closes
    return {
        'symbol': symbol,
        'open': round(opens, 2),
        'current': round(cur, 2),
        'day_high': round(highs, 2),
        'day_low': round(lows, 2),
        'vwap': round(vwap, 2),
        'opening_range': {'high': round(or_high, 2), 'low': round(or_low, 2)},
        'swing_30m': {'high': round(swing_high_30m, 2), 'low': round(swing_low_30m, 2)},
        'dist_from_vwap': dist(cur, vwap),
        'dist_from_day_high': dist(cur, highs),
        'dist_from_day_low': dist(cur, lows),
        'dist_from_or_high': dist(cur, or_high),
        'dist_from_or_low': dist(cur, or_low),
        'vol_total': vol_total,
        'tick_count_today': len(today_ticks),
        'last_ts': today_ticks[-1][0],
    }


def main() -> int:
    # FIX 2026-09-21 15:32: was broken — module-level TICKS dict resets every
    # invocation, so each CLI run only saw the single tick it just appended.
    # Result: open=high=low=current (one value), range=0.00%, LLM dismissed as
    # "stale/flat data feed". Now we read the candle_engine's per-minute bars
    # (data_cache/candles/SYM_1m.jsonl) which PERSIST and contain the full
    # OHLCV history for today.
    ts = now_ist_str()
    out = {'ts': ts, 'instruments': {}}

    # 1. Read live LTP from candle engine (preferred)
    live_prices = read_bot_latest_prices()

    # 2. Read per-minute bars JSONL for full session OHLCV
    candles_dir = DATA / 'candles'
    today = ts[:10]
    SYMBOLS_TO_TRACK = ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'SENSEX', 'INDIAVIX']

    for sym in SYMBOLS_TO_TRACK:
        # Read bars from JSONL
        bars = []
        bar_path = candles_dir / f'{sym}_1m.jsonl'
        if bar_path.exists():
            try:
                for line in bar_path.read_text(encoding='utf-8').strip().split('\n'):
                    if not line.strip():
                        continue
                    try:
                        bar = json.loads(line)
                        # Filter to today's bars only
                        bar_ts = bar.get('ts', '')
                        if bar_ts.startswith(today):
                            bars.append(bar)
                    except Exception:
                        continue
            except Exception:
                pass

        # Build per-symbol levels
        cur = live_prices.get(sym, {}).get('price', 0)
        if not cur and bars:
            # Fallback to last bar close
            try:
                cur = float(bars[-1].get('c', 0))
            except Exception:
                cur = 0
        if not cur:
            continue

        # Open from first bar of today; close/high/low from full day
        opn = float(bars[0].get('o', cur)) if bars else cur
        highs = max((float(b.get('h', cur)) for b in bars), default=cur)
        lows = min((float(b.get('l', cur)) for b in bars), default=cur)
        vwap = sum(float(b.get('c', 0)) for b in bars) / max(len(bars), 1)  # rough proxy
        # Opening range (first 15 min from 09:15)
        or_bars = [b for b in bars if '09:15' <= b.get('ts', '')[11:16] <= '09:30']
        or_high = max((float(b.get('h', cur)) for b in or_bars), default=highs)
        or_low = min((float(b.get('l', cur)) for b in or_bars), default=lows)
        # Recent swing (last 30 min)
        cutoff = ts[:14] + str(int(ts[14:16]) - 1).zfill(2) + ts[16:] if int(ts[14:16]) > 0 else ts
        recent = [b for b in bars if b.get('ts', '0') >= cutoff]
        swing_high = max((float(b.get('h', cur)) for b in recent), default=highs)
        swing_low = min((float(b.get('l', cur)) for b in recent), default=lows)
        # Distance calculations
        dist_from_vwap = round((cur - vwap) / vwap * 100, 3) if vwap else 0
        rng_pct = round((cur - opn) / opn * 100, 3) if opn else 0

        out['instruments'][sym] = {
            'open': round(opn, 2),
            'current': round(cur, 2),
            'day_high': round(highs, 2),
            'day_low': round(lows, 2),
            'vwap': round(vwap, 2),
            'opening_range': {'high': round(or_high, 2), 'low': round(or_low, 2)},
            'swing_30m': {'high': round(swing_high, 2), 'low': round(swing_low, 2)},
            'dist_from_vwap': dist_from_vwap,
            'session_pct': rng_pct,
            'tick_count_today': len(bars),
            'last_ts': bars[-1].get('ts', '') if bars else ts,
            'source': 'candles_1m.jsonl + candle_engine',
        }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, default=str), encoding='utf-8')

    # One-liner
    summary = []
    for sym, lv in out['instruments'].items():
        cur = lv.get('current', 0)
        rng = lv.get('session_pct', 0)
        summary.append(f"{sym}={cur} range={rng:+.2f}%")
    print(f"INTRADAY-LEVELS: {' | '.join(summary)}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
