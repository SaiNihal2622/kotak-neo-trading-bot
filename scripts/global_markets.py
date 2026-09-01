"""Global markets 24/7 tracker.

Polls US, Asia, Europe, commodities, crypto, currencies every 60s. Writes
data_cache/global_state.json with the latest snapshot. The watch loop
includes this in LLM context so the brain is aware of overnight moves
even when NSE is closed.

This is a 24/7 awareness layer — the bot can only PLACE orders during
NSE hours (9:15-15:30 IST Mon-Fri), but the THINKING never stops.
"""
from __future__ import annotations
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
DATA = ROOT / 'data_cache'
GLOBAL_STATE_PATH = DATA / 'global_state.json'

# Global instruments to track 24/7
GLOBAL_INSTRUMENTS = {
    # US indices (S&P, NASDAQ, Dow)
    '^GSPC': {'name': 'SPX', 'region': 'us', 'category': 'index'},
    '^IXIC': {'name': 'NASDAQ', 'region': 'us', 'category': 'index'},
    '^DJI':  {'name': 'DOW', 'region': 'us', 'category': 'index'},
    '^VIX':  {'name': 'VIX', 'region': 'us', 'category': 'vol'},
    # US sector ETFs (for sector rotation signals)
    'XLF':  {'name': 'US_FINANCIALS', 'region': 'us', 'category': 'sector'},
    'XLK':  {'name': 'US_TECH', 'region': 'us', 'category': 'sector'},
    'XLE':  {'name': 'US_ENERGY', 'region': 'us', 'category': 'sector'},
    # Asia
    '^N225': {'name': 'NIKKEI', 'region': 'asia', 'category': 'index'},
    '^HSI':  {'name': 'HANGSENG', 'region': 'asia', 'category': 'index'},
    # Commodities
    'GC=F': {'name': 'GOLD', 'region': 'global', 'category': 'commodity'},
    'CL=F': {'name': 'WTI_OIL', 'region': 'global', 'category': 'commodity'},
    'SI=F': {'name': 'SILVER', 'region': 'global', 'category': 'commodity'},
    # Crypto
    'BTC-USD': {'name': 'BTC', 'region': 'global', 'category': 'crypto'},
    'ETH-USD': {'name': 'ETH', 'region': 'global', 'category': 'crypto'},
    # Currencies (DXY for global risk appetite)
    'DX-Y.NYB': {'name': 'DXY', 'region': 'global', 'category': 'currency'},
    'USDINR=X': {'name': 'USDINR', 'region': 'india', 'category': 'currency'},
}

# Previous-state cache for detecting moves
_PREV_STATE: dict[str, float] = {}


def fetch_global_state() -> dict:
    """Fetch current prices for all global instruments. Returns full state dict."""
    import yfinance as yf
    state = {
        'ts': datetime.now().isoformat(timespec='seconds'),
        'instruments': {},
        'errors': [],
    }
    for ticker, meta in GLOBAL_INSTRUMENTS.items():
        try:
            t = yf.Ticker(ticker)
            # 2-day history so we can compute overnight change
            hist = t.history(period='2d', interval='1d')
            if hist is None or hist.empty or len(hist) < 1:
                state['errors'].append(f"{meta['name']}: no data")
                continue
            last = hist.iloc[-1]
            cur = float(last['Close'])
            # Previous close (for % change)
            if len(hist) >= 2:
                prev = float(hist['Close'].iloc[-2])
                pct_1d = (cur - prev) / prev * 100 if prev else 0
            else:
                pct_1d = 0
            # Detect move vs previous fetch (intraday for currently-open markets)
            prev_ltp = _PREV_STATE.get(ticker)
            pct_intra = ((cur - prev_ltp) / prev_ltp * 100) if prev_ltp else 0
            _PREV_STATE[ticker] = cur
            state['instruments'][ticker] = {
                'name': meta['name'],
                'region': meta['region'],
                'category': meta['category'],
                'price': cur,
                'pct_1d': round(pct_1d, 3),
                'pct_intra': round(pct_intra, 3),
            }
        except Exception as e:
            state['errors'].append(f"{meta['name']}: {str(e)[:80]}")
    return state


def get_global_context() -> dict:
    """Read the latest global state for inclusion in LLM context.
    Returns a compact summary: biggest moves, vol changes, key indices."""
    if not GLOBAL_STATE_PATH.exists():
        return {}
    try:
        s = json.loads(GLOBAL_STATE_PATH.read_text(encoding='utf-8'))
    except Exception:
        return {}
    instruments = s.get('instruments', {})
    if not instruments:
        return {}
    # Build compact summary: top 5 movers by 1-day change
    movers = []
    for ticker, data in instruments.items():
        movers.append((data.get('name', ticker), data.get('pct_1d', 0),
                      data.get('pct_intra', 0), data.get('price', 0),
                      data.get('category', '')))
    movers.sort(key=lambda m: abs(m[1]), reverse=True)
    return {
        'ts': s.get('ts'),
        'top_movers_1d': movers[:8],
        'us_market_open': _is_us_market_open(),
        'asia_market_open': _is_asia_market_open(),
        'nse_market_open': _is_nse_market_open(),
    }


def _is_us_market_open() -> bool:
    """US market hours: 9:30 AM - 4:00 PM ET = 7:00 PM - 1:30 AM IST (next day)
    Simplified: open if IST hour is in [19, 20, 21, 22, 23, 0, 1] and weekday."""
    now = datetime.now()
    if now.weekday() >= 5:  # Sat/Sun
        return False
    h = now.hour
    return h >= 19 or h < 2  # 7pm-2am IST = US market hours (with buffer)


def _is_asia_market_open() -> bool:
    """Asia hours: Nikkei 9:00-15:00 JST = 5:30-11:30 IST, HSI 9:30-16:00 HKT = 7:00-13:30 IST"""
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    h = now.hour
    return 5 <= h < 14


def _is_nse_market_open() -> bool:
    """NSE hours: 9:15-15:30 IST Mon-Fri"""
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    m = now.hour * 60 + now.minute
    return 9 * 60 + 15 <= m < 15 * 60 + 30


def write_global_state() -> dict:
    """Fetch + write global state. Returns the state dict."""
    try:
        state = fetch_global_state()
        GLOBAL_STATE_PATH.write_text(json.dumps(state, indent=2, default=str),
                                     encoding='utf-8')
        return state
    except Exception as e:
        return {'ts': datetime.now().isoformat(timespec='seconds'), 'error': str(e)[:200]}


if __name__ == '__main__':
    print("[global_markets] fetching current state...")
    state = write_global_state()
    print(f"[global_markets] {len(state.get('instruments', {}))} instruments, "
          f"{len(state.get('errors', []))} errors")
    for ticker, data in state.get('instruments', {}).items():
        print(f"  {data['name']:<18} {data['price']:>10.2f}  1d={data['pct_1d']:+.2f}%  "
              f"intra={data['pct_intra']:+.2f}%")
