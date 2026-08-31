"""Quant brain: comprehensive market analysis. Writes to data_cache/quant_brain.json."""
import yfinance as yf
import pandas as pd
import numpy as np
import json
import os
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))
DCACHE = r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache"

def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()

def rsi(s, n=14):
    d = s.diff()
    g = d.where(d > 0, 0).rolling(n).mean()
    l = -d.where(d < 0, 0).rolling(n).mean()
    rs = g / l
    return 100 - 100 / (1 + rs)

def atr(df, n=14):
    h = df['High']; l = df['Low']; c = df['Close']
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()

def bb(s, n=20, k=2):
    m = s.rolling(n).mean()
    sd = s.rolling(n).std()
    return m, m + k * sd, m - k * sd

def adx(df, n=14):
    h = df['High']; l = df['Low']; c = df['Close']
    up = h.diff(); dn = -l.diff()
    plus_dm = ((up > dn) & (up > 0)) * up
    minus_dm = ((dn > up) & (dn > 0)) * dn
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr_n = tr.rolling(n).mean()
    plus_di = 100 * plus_dm.rolling(n).mean() / atr_n
    minus_di = 100 * minus_dm.rolling(n).mean() / atr_n
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    return dx.rolling(n).mean()

def safe_round(x, n=2):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return None
    return round(float(x), n)

def analyze(sym_name, yf_sym):
    t = yf.Ticker(yf_sym)
    d = t.history(period='30d', interval='1d')
    if len(d) == 0:
        return None
    h = t.history(period='5d', interval='1h')
    spot = float(d['Close'].iloc[-1])

    # Multi-period returns
    d5 = float(d['Close'].iloc[-6]) if len(d) > 6 else float(d['Close'].iloc[0])
    d10 = float(d['Close'].iloc[-11]) if len(d) > 11 else float(d['Close'].iloc[0])
    d20 = float(d['Close'].iloc[-21]) if len(d) > 21 else float(d['Close'].iloc[0])
    ret5 = (spot/d5 - 1) * 100
    ret10 = (spot/d10 - 1) * 100
    ret20 = (spot/d20 - 1) * 100

    # EMAs
    e9 = safe_round(ema(d['Close'], 9).iloc[-1])
    e21 = safe_round(ema(d['Close'], 21).iloc[-1])
    e50 = safe_round(ema(d['Close'], 50).iloc[-1] if len(d) >= 50 else ema(d['Close'], 20).iloc[-1])
    if e9 > e21 > e50:
        trend = 'BULL'
    elif e9 < e21 < e50:
        trend = 'BEAR'
    else:
        trend = 'CHOP'

    # RSI
    r = safe_round(rsi(d['Close']).iloc[-1])
    rsi_state = 'overbought' if r > 70 else ('oversold' if r < 30 else 'neutral')

    # ADX
    a = safe_round(adx(d).iloc[-1])
    trend_strength = 'STRONG' if a > 25 else ('WEAK' if a < 20 else 'MEDIUM')

    # ATR
    a14 = safe_round(atr(d).iloc[-1])
    a14_pct = safe_round((a14 / spot) * 100)

    # Bollinger
    bb_m, bb_u, bb_l = bb(d['Close'])
    bb_mid = safe_round(bb_m.iloc[-1])
    bb_upper = safe_round(bb_u.iloc[-1])
    bb_lower = safe_round(bb_l.iloc[-1])

    # 5d range
    h5 = safe_round(d['High'].iloc[-5:].max())
    l5 = safe_round(d['Low'].iloc[-5:].min())

    # Pivot
    piv = (d['High'].iloc[-1] + d['Low'].iloc[-1] + d['Close'].iloc[-1]) / 3
    r1 = 2 * piv - d['Low'].iloc[-1]
    s1 = 2 * piv - d['High'].iloc[-1]

    # Expected 1-day move
    daily_ret = d['Close'].pct_change().dropna().iloc[-20:]
    sigma_d = safe_round(daily_ret.std())
    em_1d = safe_round(spot * sigma_d) if sigma_d else None

    # Intraday today
    intraday = t.history(period='1d', interval='5m')
    i_high = i_low = i_poc = None
    if len(intraday) > 0:
        i_high = safe_round(intraday['High'].max())
        i_low = safe_round(intraday['Low'].min())
        i_poc = safe_round((i_high + i_low) / 2)

    # 24h hourly change
    h24h_chg = None
    if len(h) > 25:
        h24h_chg = safe_round((float(h['Close'].iloc[-1]) / float(h['Close'].iloc[-25]) - 1) * 100)

    # Highest volume day in last 5 (institutional activity)
    vol_profile = []
    for i in range(min(5, len(d))):
        v = int(d['Volume'].iloc[-(i+1)])
        c = float(d['Close'].iloc[-(i+1)])
        vol_profile.append({"date": str(d.index[-(i+1)].date()), "vol": v, "close": c})
    vol_profile.sort(key=lambda x: -x['vol'])

    return {
        "symbol": sym_name, "yf_symbol": yf_sym, "spot": safe_round(spot),
        "returns": {"5d_pct": safe_round(ret5), "10d_pct": safe_round(ret10), "20d_pct": safe_round(ret20)},
        "trend": trend, "trend_strength": trend_strength, "adx": a,
        "rsi": r, "rsi_state": rsi_state,
        "ema9": e9, "ema21": e21, "ema50": e50,
        "atr_14": a14, "atr_14_pct": a14_pct,
        "bb_mid": bb_mid, "bb_upper": bb_upper, "bb_lower": bb_lower,
        "5d_high": h5, "5d_low": l5,
        "pivot": safe_round(piv), "r1": safe_round(r1), "s1": safe_round(s1),
        "expected_move_1d": em_1d, "daily_sigma_pct": sigma_d,
        "intraday_high": i_high, "intraday_low": i_low, "intraday_poc": i_poc,
        "24h_change_pct": h24h_chg,
        "vol_profile_top3": vol_profile[:3],
    }

def vix_analysis():
    try:
        v = yf.Ticker('^INDIAVIX')
        d = v.history(period='30d', interval='1d')
        if len(d) == 0:
            return None
        spot = float(d['Close'].iloc[-1])
        avg20 = float(d['Close'].iloc[-20:].mean()) if len(d) >= 20 else float(d['Close'].mean())
        hi20 = float(d['High'].iloc[-20:].max())
        lo20 = float(d['Low'].iloc[-20:].min())
        if spot < 12: regime = 'low'
        elif spot < 16: regime = 'normal'
        elif spot < 22: regime = 'elevated'
        else: regime = 'crisis'
        return {
            "current": safe_round(spot),
            "20d_avg": safe_round(avg20),
            "20d_high": safe_round(hi20),
            "20d_low": safe_round(lo20),
            "regime": regime,
            "vs_avg_pct": safe_round((spot / avg20 - 1) * 100),
        }
    except Exception as e:
        return {"error": str(e)}

def global_cues():
    out = {}
    for sym, name in [('ES=F', 'spx_fut'), ('NQ=F', 'nasdaq_fut'), ('YM=F', 'dow_fut'),
                       ('CL=F', 'crude_oil'), ('GC=F', 'gold'), ('DX-Y.NYB', 'dxy'),
                       ('^VIX', 'us_vix'), ('^TNX', 'us_10y_yield')]:
        try:
            fut = yf.Ticker(sym)
            d = fut.history(period='5d', interval='1d')
            if len(d) >= 1:
                spot = safe_round(d['Close'].iloc[-1])
                chg1d = safe_round((d['Close'].iloc[-1] / d['Close'].iloc[-2] - 1) * 100) if len(d) >= 2 else 0
                chg5d = safe_round((d['Close'].iloc[-1] / d['Close'].iloc[-5] - 1) * 100) if len(d) >= 5 else 0
                out[name] = {"spot": spot, "1d_pct": chg1d, "5d_pct": chg5d}
        except Exception:
            pass
    return out

def generate_setup_quality(nifty, bn, vix):
    """Score 0-100 how good the setup is for a given strategy. Higher = better."""
    if not nifty or not bn or not vix:
        return None
    score = 50  # baseline
    notes = []
    # Trending markets: directional setups
    if nifty['trend'] == 'BULL' and nifty['trend_strength'] == 'STRONG':
        score += 15; notes.append("NIFTY strong bull trend")
    elif nifty['trend'] == 'BEAR' and nifty['trend_strength'] == 'STRONG':
        score += 15; notes.append("NIFTY strong bear trend")
    elif nifty['trend'] == 'CHOP':
        score += 5; notes.append("NIFTY chop (range-bound, favors premium selling)")
    # VIX regime
    if vix['regime'] == 'low':
        score += 5; notes.append("Low VIX = cheap premium (favor directional buyers)")
    elif vix['regime'] == 'normal':
        score += 10; notes.append("Normal VIX = balanced (both directions OK)")
    elif vix['regime'] == 'elevated':
        score += 5; notes.append("Elevated VIX = expensive premium (favor sellers)")
    elif vix['regime'] == 'crisis':
        score -= 20; notes.append("CRISIS VIX = no-trade zone")
    # RSI extremes
    if nifty['rsi_state'] == 'oversold':
        score += 10; notes.append("NIFTY oversold = mean-reversion long")
    elif nifty['rsi_state'] == 'overbought':
        score -= 5; notes.append("NIFTY overbought = caution longs")
    return {"score": min(100, max(0, score)), "notes": notes}

def main():
    print("Pulling data...")
    nifty = analyze("NIFTY", "^NSEI")
    bnf = analyze("BANKNIFTY", "^NSEBANK")
    vix = vix_analysis()
    global_ = global_cues()
    setup = generate_setup_quality(nifty, bnf, vix)

    brain = {
        "ts": datetime.now(IST).isoformat(),
        "generated_by": "Mavis-QuantBrain",
        "nifty": nifty,
        "banknifty": bnf,
        "vix": vix,
        "global_cues": global_,
        "setup_quality": setup,
    }

    out = os.path.join(DCACHE, "quant_brain.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(brain, f, indent=2, default=str)
    print(f"Wrote {out}")
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    if nifty:
        print(f"NIFTY  {nifty['spot']:>8.2f} | trend={nifty['trend']:4} ({nifty['trend_strength']}) | RSI={nifty['rsi']:.0f} ({nifty['rsi_state']})")
        print(f"        EMA9/21/50: {nifty['ema9']:>7.2f} / {nifty['ema21']:>7.2f} / {nifty['ema50']:>7.2f}")
        print(f"        ATR(14): {nifty['atr_14']:.0f} pts ({nifty['atr_14_pct']}%) | expected 1d move: ±{nifty['expected_move_1d']:.0f} pts")
        print(f"        BB(20,2): {nifty['bb_lower']:.0f} - {nifty['bb_mid']:.0f} - {nifty['bb_upper']:.0f}")
        print(f"        5d range: {nifty['5d_low']:.0f} - {nifty['5d_high']:.0f}")
        print(f"        Pivot: {nifty['pivot']:.0f} | R1: {nifty['r1']:.0f} | S1: {nifty['s1']:.0f}")
    if bnf:
        print(f"BNF    {bnf['spot']:>8.2f} | trend={bnf['trend']:4} ({bnf['trend_strength']}) | RSI={bnf['rsi']:.0f} ({bnf['rsi_state']})")
        print(f"        EMA9/21/50: {bnf['ema9']:>7.2f} / {bnf['ema21']:>7.2f} / {bnf['ema50']:>7.2f}")
        print(f"        ATR(14): {bnf['atr_14']:.0f} pts ({bnf['atr_14_pct']}%) | expected 1d move: ±{bnf['expected_move_1d']:.0f} pts")
    if vix:
        print(f"VIX    {vix['current']:>5.2f} | regime={vix['regime']} | 20d avg={vix['20d_avg']} | {vix['vs_avg_pct']:+.1f}% vs avg")
    if global_:
        print()
        print("GLOBAL:")
        for k, v in global_.items():
            print(f"  {k:15}: {v['spot']:>9.2f}  1d {v['1d_pct']:+5.2f}%  5d {v['5d_pct']:+5.2f}%")
    if setup:
        print()
        print(f"SETUP QUALITY: {setup['score']}/100")
        for n in setup['notes']:
            print(f"  - {n}")

if __name__ == "__main__":
    main()
