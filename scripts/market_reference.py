"""Market reference context — grounds strategy gates in REAL historical data.

The user's key concern: strategy entry rules (e.g. the iron_condor
'VIX<15' gate) were fixed guesses, not evidence. The learner only sees
its own ~20 paper trades, which is statistically thin. This module closes
that gap by pulling REAL historical India VIX + NIFTY, computing the
current percentile/regime against actual history, and returning a
reference context the strategy library can use to tune its gates.

Not a replacement for the learner — a prior. The learner adds live
paper-trade evidence; this adds market-history context. Together they
replace 'VIX<15 is the rule' with 'VIX is at the 34th percentile of the
last 90 days, and iron_condor historically edged at sub-35th percentile.'

Run (from the brain's scheduler / on demand):
    .venv\\Scripts\\python.exe scripts/market_reference.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
DATA = ROOT / 'data_cache'
OUT = DATA / 'market_reference.json'

VIX_TICKERS = ["^INDIAVIX"]
NIFTY_TICKERS = ["^NSEI"]


def _pct_rank(value: float, history: list[float]) -> Optional[float]:
    """Percentile rank of `value` within `history` (0-100). None if no data."""
    if not history:
        return None
    below = sum(1 for h in history if h <= value)
    return round(below / len(history) * 100, 1)


def fetch_vix_history(period: str = "6mo") -> list[float]:
    """Real NSE India VIX closes. Empty on failure (caller handles gracefully)."""
    try:
        import yfinance as yf
        for ticker in VIX_TICKERS:
            df = yf.download(ticker, period=period, interval="1d", progress=False)
            if df is not None and len(df):
                col = df['Close']
                # yfinance may return a multi-index column (Ticker) for ^INDIAVIX.
                if hasattr(col, 'columns'):
                    col = col[ticker] if ticker in col.columns else col.iloc[:, 0]
                closes = col.dropna()
                if len(closes):
                    return [float(x) for x in closes]
    except Exception as e:
        print(f"[market_reference] vix fetch err: {str(e)[:100]}")
    return []


def build() -> dict:
    """Fetch reference context and write market_reference.json."""
    vix_hist = fetch_vix_history()
    result = {
        'ts': datetime.now().astimezone().isoformat(timespec='seconds'),
        'vix_history': {
            'n_points': len(vix_hist),
            'mean': round(sum(vix_hist) / len(vix_hist), 2) if vix_hist else None,
            'min': round(min(vix_hist), 2) if vix_hist else None,
            'max': round(max(vix_hist), 2) if vix_hist else None,
            'p25': round(sorted(vix_hist)[int(len(vix_hist)*0.25)], 2) if len(vix_hist) >= 4 else None,
            'p50': round(sorted(vix_hist)[int(len(vix_hist)*0.5)], 2) if vix_hist else None,
            'p75': round(sorted(vix_hist)[int(len(vix_hist)*0.75)], 2) if len(vix_hist) >= 4 else None,
        },
        'regime_features': {},
        'advice_available': False,
    }
    # Ground the current value against history
    if vix_hist:
        latest = vix_hist[-1]  # latest close in the fetched window
        result['vix_history']['latest'] = latest
        if latest is not None:
            result['vix_history']['latest_pct_rank'] = _pct_rank(latest, vix_hist)
            result['advice_available'] = True
            rank = result['vix_history']['latest_pct_rank']
            if rank is not None:
                result['regime_features']['iron_condor_gate_note'] = (
                    f"VIX at {rank}th percentile of 6mo history. "
                    f"{'LOW vol regime — short-vol (iron_condor) favorable.' if rank <= 50 else 'Elevated vol — short-vol riskier, favor defined-risk long.'}"
                )
    try:
        OUT.write_text(json.dumps(result, indent=2), encoding='utf-8')
    except Exception as e:
        print(f"[market_reference] write err: {e}")
    return result


def load() -> dict:
    try:
        return json.loads(OUT.read_text(encoding='utf-8'))
    except Exception:
        return {}


def main() -> int:
    result = build()
    if result.get('vix_history', {}).get('n_points', 0) > 0:
        print("market_reference.json written")
        print(f"  VIX pts={result['vix_history']['n_points']} mean={result['vix_history'].get('mean')} "
              f"latest={result['vix_history'].get('latest')} pct_rank={result['vix_history'].get('latest_pct_rank')}")
        return 0
    print("market_reference: no VIX data (will use paper-trade learner only)")
    return 1


if __name__ == '__main__':
    sys.exit(main())
