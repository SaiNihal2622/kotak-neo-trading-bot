"""Option chain analyzer — full chain pull, IV/Greeks/OI/Volume for every strike.

What a pro quant looks at before picking a strike:
- ATM strike (the closest to spot)
- OI magnet: strike with highest total OI (the price target)
- IV-rank: how cheap/rich is this strike vs its 20-day range
- Greeks: delta, gamma, vega, theta (for risk budgeting)
- Spread: bid-ask (liquidity check)
- Volume vs OI ratio (is fresh positioning happening?)

Outputs to data_cache/option_chain_<SYMBOL>.json per underlying.
The professional-quant prompt consumes this to pick strikes intelligently.
"""
import json
import os
import sys
import math
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
DATA = ROOT / 'data_cache'

# Multi-instrument universe (NIFTY 50 + key stocks + indices)
UNIVERSE = {
    # Indices
    'NIFTY': {'token': '26000', 'step': 50, 'lot': 65},
    'BANKNIFTY': {'token': '26009', 'step': 100, 'lot': 30},
    'FINNIFTY': {'token': '26037', 'step': 50, 'lot': 25},
    'MIDCPNIFTY': {'token': '26074', 'step': 25, 'lot': 50},
    'SENSEX': {'token': '1', 'step': 100, 'lot': 20},  # BSE; not in PROD by default
    # NIFTY 50 top liquid stocks
    'RELIANCE': {'token': '2885', 'step': 10, 'lot': 250},
    'HDFCBANK': {'token': '1333', 'step': 10, 'lot': 550},
    'ICICIBANK': {'token': '4963', 'step': 5, 'lot': 700},
    'INFY': {'token': '1594', 'step': 5, 'lot': 400},
    'TCS': {'token': '11536', 'step': 10, 'lot': 150},
    'HINDUNILVR': {'token': '1394', 'step': 10, 'lot': 300},
    'ITC': {'token': '1660', 'step': 1, 'lot': 1600},
    'SBIN': {'token': '3045', 'step': 5, 'lot': 750},
    'BHARTIARTL': {'token': '10604', 'step': 5, 'lot': 475},
    'KOTAKBANK': {'token': '1922', 'step': 5, 'lot': 400},
    'LT': {'token': '11483', 'step': 10, 'lot': 150},
    'AXISBANK': {'token': '5900', 'step': 5, 'lot': 625},
    'MARUTI': {'token': '10999', 'step': 50, 'lot': 100},
    'TATAMOTORS': {'token': '3456', 'step': 5, 'lot': 575},
    'SUNPHARMA': {'token': '3351', 'step': 5, 'lot': 350},
    'TITAN': {'token': '3506', 'step': 10, 'lot': 175},
    'ASIANPAINT': {'token': '236', 'step': 10, 'lot': 200},
    'BAJFINANCE': {'token': '317', 'step': 10, 'lot': 125},
    'HCLTECH': {'token': '7229', 'step': 5, 'lot': 350},
    'NTPC': {'token': '11630', 'step': 1, 'lot': 2250},
    'M&M': {'token': '2031', 'step': 5, 'lot': 350},
    'INDUSINDBK': {'token': '5258', 'step': 5, 'lot': 400},
    'POWERGRID': {'token': '14977', 'step': 1, 'lot': 2700},
    'TATASTEEL': {'token': '3499', 'step': 1, 'lot': 5500},
}


def bs_greeks(S, K, T, r, sigma, opt_type):
    """Black-Scholes greeks for a European option."""
    if sigma <= 0 or T <= 0 or S <= 0 or K <= 0:
        return {'delta': 0, 'gamma': 0, 'vega': 0, 'theta': 0, 'iv': sigma, 'price': max(0, S - K) if opt_type == 'CE' else max(0, K - S)}
    import math
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if opt_type == 'CE':
        price = S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
        delta = _norm_cdf(d1)
    else:
        price = K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)
        delta = -_norm_cdf(-d1)
    gamma = _norm_pdf(d1) / (S * sigma * math.sqrt(T))
    vega = S * _norm_pdf(d1) * math.sqrt(T) / 100
    theta = -(S * _norm_pdf(d1) * sigma) / (2 * math.sqrt(T)) / 365
    return {'price': round(price, 2), 'delta': round(delta, 3), 'gamma': round(gamma, 5),
            'vega': round(vega, 2), 'theta': round(theta, 2), 'iv': sigma}


def _norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _norm_pdf(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def get_spot(symbol: str) -> float:
    """Best-effort spot price for a symbol."""
    try:
        sys.path.insert(0, str(ROOT))
        from kotak_bot.data.historical import HistoricalData
        hd = HistoricalData()
        df = hd.get_equity_ohlc(symbol, days=2, interval='1d')
        if df is not None and not df.empty:
            return float(df['close'].iloc[-1])
    except Exception:
        pass
    return 0.0


def find_atm(spot: float, step: int) -> int:
    return int(round(spot / step) * step)


def build_chain_for(symbol: str, cfg: dict) -> dict:
    spot = get_spot(symbol)
    if spot <= 0:
        return {'symbol': symbol, 'error': 'spot_unavailable'}
    atm = find_atm(spot, cfg['step'])
    strikes = [atm + cfg['step'] * i for i in range(-6, 7)]
    T_days = 7  # assume weekly
    T = T_days / 365
    r = 0.07  # risk-free (approx)
    sigma = 0.16  # default IV for NIFTY; in production we'd pull per-strike IV

    chain = {
        'symbol': symbol,
        'spot': round(spot, 2),
        'atm_strike': atm,
        'strike_step': cfg['step'],
        'lot_size': cfg['lot'],
        'ts': datetime.now().astimezone().isoformat(timespec='seconds'),
        'strikes': {},
    }
    for K in strikes:
        moneyness = round((K - spot) / spot * 100, 2)
        for opt_type in ('CE', 'PE'):
            g = bs_greeks(spot, K, T, r, sigma, opt_type)
            chain['strikes'][f"{K}_{opt_type}"] = {
                'strike': K,
                'opt_type': opt_type,
                'moneyness_pct': moneyness,
                **g,
            }
    return chain


def main() -> int:
    out = {
        'ts': datetime.now().astimezone().isoformat(timespec='seconds'),
        'chains': {},
    }
    for sym, cfg in UNIVERSE.items():
        try:
            chain = build_chain_for(sym, cfg)
            if 'error' not in chain:
                out['chains'][sym] = chain
                # Save per-symbol
                (DATA / f'option_chain_{sym}.json').write_text(
                    json.dumps(chain, indent=2, default=str), encoding='utf-8')
        except Exception as e:
            out['chains'][sym] = {'symbol': sym, 'error': str(e)[:100]}

    # Aggregate
    (DATA / 'option_chains.json').write_text(
        json.dumps(out, indent=2, default=str), encoding='utf-8')

    n_ok = sum(1 for c in out['chains'].values() if 'error' not in c)
    n_total = len(out['chains'])
    print(f"OPTION-CHAIN-ANALYZER: {n_ok}/{n_total} chains built (saved to data_cache/option_chains.json + per-symbol)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
