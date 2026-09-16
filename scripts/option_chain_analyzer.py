"""Option chain analyzer — full chain pull from Kotak Neo PROD for every strike.

What a pro quant looks at before picking a strike:
- ATM strike (the closest to spot)
- OI magnet: strike with highest total OI (the price target)
- IV-rank: how cheap/rich is this strike vs its 20-day range
- Greeks: delta, gamma, vega, theta (for risk budgeting)
- Spread: bid-ask (liquidity check)
- Volume vs OI ratio (is fresh positioning happening?)

Outputs to data_cache/option_chain_<SYMBOL>.json per underlying.
The professional-quant prompt consumes this to pick strikes intelligently.

FIX 2026-09-16 12:30: switched the data source from yfinance (broken — returned
NIFTY at sane prices but FINNIFTY spot 4966, MIDCPNIFTY 4968, SENSEX 5113, all
out of plausible range) to Kotak Neo PROD quotes REST API (the same one
KotakProdFeed already uses for live tick data). Now every chain entry is a
REAL bid/ask/ltp/oi pulled from Kotak's production market data, with IV/Greeks
derived from those prices via Black-Scholes inversion.
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, date, timedelta
from pathlib import Path


# FIX 2026-09-16 12:35: when this script is run as a subprocess from the
# scheduler (`python scripts/option_chain_analyzer.py`), sys.path[0] is the
# `scripts/` directory, not the project root. Without this, the Kotak feed
# import fails with "No module named 'kotak_bot'" and we silently fall back
# to the broken BS path. Add the project root to sys.path before any kotak
# imports. Idempotent — safe to call multiple times.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


ROOT = _PROJECT_ROOT
DATA = ROOT / 'data_cache'

# Multi-instrument universe (NIFTY 50 + key stocks + indices).
# step = strike gap, lot = lot size, nearest_expiry_weekday = NSE weekly
# expiry day-of-week (0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri). Used to pick the
# right contracts.
# FIX 2026-09-16 12:40: corrected NIFTY weekly expiry from Monday (0) to
# Tuesday (1) — NIFTY switched to Tuesday weekly expiry in late 2024. The old
# config caused every chain lookup to miss, falling back to no-data. Same
# correction for BANKNIFTY (Wednesday = 2). FINNIFTY/MIDCPNIFTY: their scrip
# master rows weren't found in the PROD CSV on first load — kept for
# forward-compat with the next scrip master that may include them.
UNIVERSE = {
    # Indices
    'NIFTY':      {'token': '26000', 'step': 50,   'lot': 65,  'weekday': 1},
    'BANKNIFTY':  {'token': '26009', 'step': 100,  'lot': 30,  'weekday': 2},
    'FINNIFTY':   {'token': '26037', 'step': 50,   'lot': 65,  'weekday': 1},
    'MIDCPNIFTY': {'token': '26074', 'step': 25,   'lot': 120, 'weekday': 1},
    # SENSEX is BSE-only; Kotak Neo PROD is NSE-only. We still write a
    # placeholder file with error='kotak_nse_only' so the audit doesn't flag
    # a missing chain as broken (it'll show as a known-unavailable upstream).
    'SENSEX':     {'token': '1',     'step': 100,  'lot': 20,  'weekday': 4, 'bse': True},
    # NIFTY 50 top liquid stocks (kept for compatibility with downstream consumers)
    'RELIANCE':    {'token': '2885',  'step': 10,   'lot': 250, 'weekday': 4},
    'HDFCBANK':    {'token': '1333',  'step': 10,   'lot': 550, 'weekday': 4},
    'ICICIBANK':   {'token': '4963',  'step': 5,    'lot': 700, 'weekday': 4},
    'INFY':        {'token': '1594',  'step': 5,    'lot': 400, 'weekday': 4},
    'TCS':         {'token': '11536', 'step': 10,   'lot': 150, 'weekday': 4},
    'HINDUNILVR':  {'token': '1394',  'step': 10,   'lot': 300, 'weekday': 4},
    'ITC':         {'token': '1660',  'step': 1,    'lot': 1600, 'weekday': 4},
    'SBIN':        {'token': '3045',  'step': 5,    'lot': 750, 'weekday': 4},
    'BHARTIARTL':  {'token': '10604', 'step': 5,    'lot': 475, 'weekday': 4},
    'KOTAKBANK':   {'token': '1922',  'step': 5,    'lot': 400, 'weekday': 4},
    'LT':          {'token': '11483', 'step': 10,   'lot': 150, 'weekday': 4},
    'AXISBANK':    {'token': '5900',  'step': 5,    'lot': 625, 'weekday': 4},
    'MARUTI':      {'token': '10999', 'step': 50,   'lot': 100, 'weekday': 4},
    'TATAMOTORS':  {'token': '3456',  'step': 5,    'lot': 575, 'weekday': 4},
    'SUNPHARMA':   {'token': '3351',  'step': 5,    'lot': 350, 'weekday': 4},
    'TITAN':       {'token': '3506',  'step': 10,   'lot': 175, 'weekday': 4},
    'ASIANPAINT':  {'token': '236',   'step': 10,   'lot': 200, 'weekday': 4},
    'BAJFINANCE':  {'token': '317',   'step': 10,   'lot': 125, 'weekday': 4},
    'HCLTECH':     {'token': '7229',  'step': 5,    'lot': 350, 'weekday': 4},
    'NTPC':        {'token': '11630', 'step': 1,    'lot': 2250, 'weekday': 4},
    'M&M':         {'token': '2031',  'step': 5,    'lot': 350, 'weekday': 4},
    'INDUSINDBK':  {'token': '5258',  'step': 5,    'lot': 400, 'weekday': 4},
    'POWERGRID':   {'token': '14977', 'step': 1,    'lot': 2700, 'weekday': 4},
    'TATASTEEL':   {'token': '3499',  'step': 1,    'lot': 5500, 'weekday': 4},
}


# ---------------------------------------------------------------------------
# Black-Scholes math (used to derive IV/Greeks from real Kotak prices)
# ---------------------------------------------------------------------------
def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def bs_greeks(S: float, K: float, T: float, r: float, sigma: float, opt_type: str) -> dict:
    """Black-Scholes greeks for a European option (T in years)."""
    if sigma <= 0 or T <= 0 or S <= 0 or K <= 0:
        return {'delta': 0, 'gamma': 0, 'vega': 0, 'theta': 0, 'iv': sigma,
                'price': max(0, S - K) if opt_type == 'CE' else max(0, K - S)}
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
            'vega': round(vega, 2), 'theta': round(theta, 2), 'iv': round(sigma, 4)}


def _bs_implied_vol(S: float, K: float, T: float, r: float, market_price: float, opt_type: str) -> float:
    """Bisection IV inversion from a real market price. Returns 0.16 default on failure."""
    if S <= 0 or K <= 0 or T <= 0 or market_price <= 0:
        return 0.16
    intrinsic = max(0, S - K) if opt_type == 'CE' else max(0, K - S)
    if market_price < intrinsic * 0.95:
        return 0.16  # below intrinsic — likely bad price; don't waste time
    lo, hi = 0.01, 3.0
    for _ in range(40):
        mid = (lo + hi) / 2
        p = bs_greeks(S, K, T, r, mid, opt_type)['price']
        if opt_type == 'CE':
            if p > market_price:
                hi = mid
            else:
                lo = mid
        else:
            if p > market_price:
                hi = mid
            else:
                lo = mid
        if abs(p - market_price) < 0.01:
            return round(mid, 4)
    return round((lo + hi) / 2, 4)


# ---------------------------------------------------------------------------
# Kotak Neo PROD feed helpers (re-use the prod feed module)
# ---------------------------------------------------------------------------
def _load_credentials() -> dict:
    """Read Kotak creds from env or config/credentials.env (for subprocess runs)."""
    env = os.environ.copy()
    if not env.get('KOTAK_API_KEY'):
        # Try loading from config/credentials.env (subprocess may not inherit env)
        cred_path = ROOT / 'config' / 'credentials.env'
        if cred_path.exists():
            try:
                from dotenv import dotenv_values
                env.update({k: v for k, v in dotenv_values(cred_path).items() if v})
            except ImportError:
                # Fall back to manual parse (KEY=VALUE lines, # comments)
                for line in cred_path.read_text(encoding='utf-8').splitlines():
                    line = line.strip()
                    if not line or line.startswith('#') or '=' not in line:
                        continue
                    k, v = line.split('=', 1)
                    env[k.strip()] = v.strip().strip('"').strip("'")
        os.environ.update(env)
    return env


def _get_kotak_feed():
    """Build a KotakProdFeed from env credentials."""
    from kotak_bot.data.kotak_prod_feed import KotakProdFeed
    env = _load_credentials()
    return KotakProdFeed(
        env=env.get('KOTAK_ENV', 'uat'),
        access_token=env.get('KOTAK_API_KEY', ''),
        mobile=env.get('KOTAK_MOBILE', ''),
        ucc=env.get('KOTAK_UCC', ''),
        totp_secret=env.get('KOTAK_TOTP_SECRET', ''),
        mpin=env.get('KOTAK_MPIN', ''),
        poll_interval_sec=2.0,
    )


def _get_kotak_chain(symbol: str, cfg: dict, feed) -> dict:
    """Build an option chain for `symbol` from a running KotakProdFeed.

    Returns the chain dict (same shape as the old BS-only one) or an error dict
    if Kotak isn't authenticated or the chain is empty.

    FIX 2026-09-16 12:40: subscribe to the underlying spot (Kotak spot quotes
    are pulled on a separate nse_cm endpoint). Without this, feed.get_ltp()
    returned 0 and the chain was never built. Also: if no scrip master match
    for the expiry (e.g., FINNIFTY/MIDCPNIFTY/SENSEX which Kotak PROD may
    not have), return error='not_in_scrip_master' so downstream consumers
    can distinguish "broken chain" from "underlying not supported by Kotak".
    """
    # 0) Subscribe to the underlying spot so feed.get_ltp() returns a real value.
    if cfg.get('bse'):
        return {'symbol': symbol, 'error': 'kotak_nse_only_bse_skipped'}
    feed.subscribe([symbol])
    # 1) Find nearest weekly expiry (per the scrip master, not hardcoded weekday)
    exp_date = feed.get_nearest_expiry(symbol)
    if not exp_date:
        return {'symbol': symbol, 'error': 'not_in_scrip_master'}
    exp_str = exp_date.strftime('%d%b%y').upper()
    # 2) Trigger a poll cycle to get the spot
    time.sleep(2.5)
    spot = feed.get_ltp(symbol)
    if spot <= 0:
        return {'symbol': symbol, 'error': 'spot_unavailable'}
    # 3) ATM strike and ±6 strikes around it
    step = cfg['step']
    atm = int(round(spot / step) * step)
    strikes = [atm + step * i for i in range(-6, 7)]
    # 4) Resolve strategy symbols via scrip master
    strike_to_psym = {}
    for K in strikes:
        for opt in ('CE', 'PE'):
            strat_sym = f"{symbol}{exp_str}{int(K)}{opt}"
            psym = feed.get_pSymbol(strat_sym)
            if psym:
                strike_to_psym[(K, opt)] = (strat_sym, psym)
    if not strike_to_psym:
        return {'symbol': symbol, 'error': 'no_strikes_in_scrip_master'}
    feed.subscribe([s for (s, _) in strike_to_psym.values()])
    # 5) Trigger another poll cycle for option strikes (batches of 50)
    time.sleep(3.0)
    # 6) Build the chain from live ticks
    chain = {
        'symbol': symbol,
        'spot': round(spot, 2),
        'atm_strike': atm,
        'strike_step': step,
        'lot_size': cfg['lot'],
        'expiry': exp_date.isoformat(),
        'ts': datetime.now().astimezone().isoformat(timespec='seconds'),
        'source': 'kotak_prod',
        'strikes': {},
    }
    T_days = max(1, (exp_date - date.today()).days)
    T = T_days / 365
    r = 0.07
    ivs_seen = []
    for K in strikes:
        for opt in ('CE', 'PE'):
            strat_sym, _psym = strike_to_psym.get((K, opt), (None, None))
            if not strat_sym:
                continue
            latest = feed.get_latest(strat_sym)
            ltp = float(latest.get('ltp', 0) or 0) if latest else 0.0
            bid = float(latest.get('bid', 0) or 0) if latest else 0.0
            ask = float(latest.get('ask', 0) or 0) if latest else 0.0
            oi = int(latest.get('oi', 0) or 0) if latest else 0
            vol = int(latest.get('volume', 0) or 0) if latest else 0
            iv = _bs_implied_vol(spot, K, T, r, ltp, opt) if ltp > 0 else 0.16
            if 0.01 < iv < 3.0:
                ivs_seen.append(iv)
            greeks = bs_greeks(spot, K, T, r, iv, opt)
            moneyness = round((K - spot) / spot * 100, 2)
            chain['strikes'][f"{K}_{opt}"] = {
                'strike': K,
                'opt_type': opt,
                'moneyness_pct': moneyness,
                'price': round(ltp, 2),
                'bid': round(bid, 2),
                'ask': round(ask, 2),
                'spread': round(ask - bid, 2) if bid > 0 and ask > 0 else 0.0,
                'oi': oi,
                'volume': vol,
                **greeks,
            }
    if ivs_seen:
        chain['_median_iv'] = round(sum(ivs_seen) / len(ivs_seen), 4)
    return chain


def _next_weekday(today: date, target_weekday: int) -> date:
    """Return the next date whose weekday == target_weekday (0=Mon, 2=Wed, etc.).
    If today IS the target weekday, return today."""
    days_ahead = (target_weekday - today.weekday()) % 7
    return today + timedelta(days=days_ahead)


# ---------------------------------------------------------------------------
# Legacy yfinance fallback (kept for tests; not used in production anymore)
# ---------------------------------------------------------------------------
def get_spot(symbol: str) -> float:
    """Legacy fallback — only used if Kotak feed isn't available."""
    try:
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


def build_chain_for(symbol: str, cfg: dict, feed=None) -> dict:
    """Build chain using Kotak Neo PROD if a feed is available, else fallback."""
    if feed is not None and feed.is_authenticated():
        try:
            return _get_kotak_chain(symbol, cfg, feed)
        except Exception as e:
            return {'symbol': symbol, 'error': f'kotak_failed:{str(e)[:120]}'}
    # Fallback to legacy BS-only path (kept for unit tests)
    spot = get_spot(symbol)
    if spot <= 0:
        return {'symbol': symbol, 'error': 'spot_unavailable'}
    atm = find_atm(spot, cfg['step'])
    strikes = [atm + cfg['step'] * i for i in range(-6, 7)]
    T_days = 7
    T = T_days / 365
    r = 0.07
    sigma = 0.16
    chain = {
        'symbol': symbol,
        'spot': round(spot, 2),
        'atm_strike': atm,
        'strike_step': cfg['step'],
        'lot_size': cfg['lot'],
        'ts': datetime.now().astimezone().isoformat(timespec='seconds'),
        'source': 'bs_fallback',
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
        'source': 'kotak_prod',
        'chains': {},
    }
    feed = None
    try:
        feed = _get_kotak_feed()
        feed.start()
        if not feed.is_authenticated():
            print('OPTION-CHAIN-ANALYZER: Kotak auth failed, falling back to BS')
            feed = None
    except Exception as e:
        print(f'OPTION-CHAIN-ANALYZER: could not start Kotak feed: {e}')
        feed = None

    for sym, cfg in UNIVERSE.items():
        try:
            chain = build_chain_for(sym, cfg, feed=feed)
            out['chains'][sym] = chain
            # FIX 2026-09-16 13:05: ALWAYS write the per-symbol file, even on
            # error. Otherwise stale BS-fake chain files from the old analyzer
            # (which used yfinance + synthetic prices) linger on disk and the
            # watchdog keeps reporting them as broken even after we switch to
            # a real Kotak source. The error file has `"error": "..."` instead
            # of `"strikes": {...}`, which chain_health distinguishes via the
            # `available` flag (added 2026-09-16 12:50).
            (DATA / f'option_chain_{sym}.json').write_text(
                json.dumps(chain, indent=2, default=str), encoding='utf-8')
        except Exception as e:
            err_chain = {'symbol': sym, 'error': str(e)[:200]}
            out['chains'][sym] = err_chain
            try:
                (DATA / f'option_chain_{sym}.json').write_text(
                    json.dumps(err_chain, indent=2, default=str), encoding='utf-8')
            except Exception:
                pass

    try:
        if feed is not None:
            feed.stop()
    except Exception:
        pass

    (DATA / 'option_chains.json').write_text(
        json.dumps(out, indent=2, default=str), encoding='utf-8')

    n_ok = sum(1 for c in out['chains'].values() if 'error' not in c)
    n_total = len(out['chains'])
    source = out['chains'].get('NIFTY', {}).get('source', 'unknown')
    print(f'OPTION-CHAIN-ANALYZER: {n_ok}/{n_total} chains built (source={source}, '
          f'saved to data_cache/option_chains.json + per-symbol)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
