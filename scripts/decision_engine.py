"""decision_engine.py — Clean, reasoning-based trade selection (REBUILD).

Replaces the template-based strategy_library selector. Instead of cycling
through 5 fixed templates with hardcoded thresholds, this engine:

  1. Reads the rich market data (candles, indicators, regime, news, VIX)
  2. Computes a market REGIME (trend / range / momentum / vol)
  3. Scores EVERY candidate setup by edge quality (0-100)
  4. Takes ONLY the single best setup if its edge is genuinely high
     (else HOLD — preserves capital)
  5. Sizes by risk (vol-targeted, 1-lot minimum)

The brain calls this with the full context and gets back ONE decision:
  {action: OPEN/CLOSE/HOLD, structure, symbol, qty, price, edge_score,
   rationale, regime}

No templates. No hardcoded "if VIX<18 then iron_condor". Pure reasoning
over real data.
"""
from __future__ import annotations
import json
import math
from datetime import datetime, time as dtime
from pathlib import Path
from typing import Optional, Dict, Any, List

DATA = Path("data_cache")
ROOT = Path(__file__).resolve().parent.parent  # project root (kotak-neo-bot)


def _read_candle_history(sym: str = "NIFTY", timeframe: str = "1m", n: int = 60) -> list:
    """Read real OHLCV bar history from the candle JSONL files.

    Returns a list of {open, high, low, close, volume} dicts (oldest first).
    This is how the system detects research-backed candle patterns — reading
    the full history, not the 3-bar in-memory snapshot.
    """
    p = DATA / "candles" / f"{sym}_{timeframe}.jsonl"
    if not p.exists():
        return []
    rows = []
    try:
        for line in p.read_text(encoding="utf-8").splitlines()[-n:]:
            b = json.loads(line)
            rows.append({
                "open": b.get("o"), "high": b.get("h"),
                "low": b.get("l"), "close": b.get("c"),
                "volume": b.get("v", 0),
            })
    except Exception:
        pass
    return [r for r in rows if r.get("close") is not None]


def _detect_candle_patterns(bars: list) -> Dict[str, float]:
    """Detect research-backed candle patterns (pandas_ta, 130+ patterns).

    Returns a dict of pattern -> last value (-1, 0, +1). Only includes
    patterns that FIRED on the latest bar. Empty if bars too few.
    """
    if len(bars) < 3:
        return {}
    try:
        import pandas as pd
        import pandas_ta as ta
        df = pd.DataFrame(bars)
        out = {}
        for pat in ["cdl_doji", "cdl_engulfing", "cdl_hammer", "cdl_invertedhammer",
                    "cdl_shootingstar", "cdl_marubozu", "cdl_morningstar", "cdl_eveningstar",
                    "cdl_threewhitesoldiers", "cdl_threeblackcrows", "cdl_piercing",
                    "cdl_darkcloudcover", "cdl_harami", "cdl_hangingman", "cdl_star",
                    "cdl_beltabhold"]:
            try:
                res = getattr(ta.cdl_pattern, pat)(df["open"], df["high"], df["low"], df["close"])
                last = float(res.iloc[-1])
                if last != 0:
                    out[pat] = last
            except Exception:
                continue
        return out
    except Exception:
        return {}


# ===== Kronos forecast (predictive edge) =====

_KRONOS = {"loaded": False, "predictor": None, "last_forecast": None, "last_ts": 0}


def _kronos_forecast(bars: list, pred_len: int = 5) -> dict | None:
    """Use the Kronos foundation model to forecast the next N candles.

    Returns {direction, next_close, last_close, pct} or None if unavailable.
    Kronos is a financial candlestick foundation model (trained on 45+
    exchanges) that forecasts future OHLCV from historical K-lines.
    """
    if len(bars) < 20:
        return None
    try:
        import time as _t
        # Cache: only re-forecast every 60s (model is slow on CPU)
        if _KRONOS["last_forecast"] and _t.time() - _KRONOS["last_ts"] < 60:
            return _KRONOS["last_forecast"]
        if not _KRONOS["loaded"]:
            import sys as _sys
            _sys.path.insert(0, str(ROOT.parent / "kronos"))
            from model import Kronos, KronosTokenizer, KronosPredictor
            _KRONOS["tokenizer"] = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-2k")
            _KRONOS["model"] = Kronos.from_pretrained("NeoQuasar/Kronos-mini")
            _KRONOS["predictor"] = KronosPredictor(_KRONOS["model"], _KRONOS["tokenizer"], max_context=512)
            _KRONOS["loaded"] = True
        import pandas as pd
        import datetime
        df = pd.DataFrame(bars[-20:])
        ts = pd.Series([datetime.datetime.now() - datetime.timedelta(minutes=len(df)-i) for i in range(len(df))])
        y_ts = pd.Series([datetime.datetime.now() + datetime.timedelta(minutes=i+1) for i in range(pred_len)])
        pred = _KRONOS["predictor"].predict(df=df, x_timestamp=ts, y_timestamp=y_ts,
                                             pred_len=pred_len, T=1.0, top_p=0.9, sample_count=1)
        last_close = float(df["close"].iloc[-1])
        next_close = float(pred["close"].iloc[-1])
        res = {
            "direction": "UP" if next_close > last_close else "DOWN",
            "next_close": next_close, "last_close": last_close,
            "pct": (next_close - last_close) / last_close * 100 if last_close else 0,
        }
        _KRONOS["last_forecast"] = res
        _KRONOS["last_ts"] = _t.time()
        return res
    except Exception as e:
        return None


# ===== Regime detection =====

def _regime(candles: dict, intraday: dict, vix: float) -> Dict[str, Any]:
    """Classify the current market regime from real indicators."""
    n = (candles.get("symbols") or {}).get("NIFTY") or {}
    ind = n.get("indicators") or {}
    spot = float(n.get("ltp") or 0)
    session_pct = float(n.get("session_pct") or 0)
    adx = float(ind.get("adx") or 0)
    rsi = float(ind.get("rsi_14") or 50)
    ema9 = float(ind.get("ema_9") or spot)
    ema21 = float(ind.get("ema_21") or spot)
    ema50 = float(ind.get("ema_50") or spot)
    vwap = float(ind.get("vwap") or spot)
    vwap_dev = float(ind.get("vwap_dev_pct") or 0)
    atr = float(ind.get("atr_14") or 0)
    macd = ind.get("macd") or {}
    macd_hist = float(macd.get("histogram") or macd.get("hist") or 0)

    # Trend strength
    trending = adx > 25
    ema_bull = ema9 > ema21 > ema50
    ema_bear = ema9 < ema21 < ema50
    macd_bull = macd_hist > 0
    macd_bear = macd_hist < 0

    # Volatility regime
    if vix >= 20:
        vol = "high"
    elif vix >= 15:
        vol = "elevated"
    else:
        vol = "low"

    # Direction
    if trending and (ema_bull or macd_bull):
        direction = "bullish"
    elif trending and (ema_bear or macd_bear):
        direction = "bearish"
    elif abs(session_pct) < 0.5 and not trending:
        direction = "range"
    else:
        direction = "mixed"

    # Research-backed candle patterns from the full history
    try:
        patterns = _detect_candle_patterns(_read_candle_history())
    except Exception:
        patterns = {}

    # Kronos foundation model forecast (predictive edge)
    try:
        kf = _kronos_forecast(_read_candle_history())
    except Exception:
        kf = None

    # Raw bar history for breakout / range_fade / pullback strategies
    try:
        _bars = _read_candle_history()
    except Exception:
        _bars = []

    return {
        "trending": trending,
        "_bars": _bars,
        "direction": direction,
        "vol": vol,
        "adx": adx,
        "rsi": rsi,
        "ema_bull": ema_bull,
        "ema_bear": ema_bear,
        "macd_bull": macd_bull,
        "macd_bear": macd_bear,
        "spot": spot,
        "session_pct": session_pct,
        "vwap_dev": vwap_dev,
        "atr": atr,
        "vwap": vwap,
        "patterns": patterns,
        "forecast": kf,
        # ---- Full-chain metrics (Option B: genuinely use the option chain) ----
        "chain": _chain_metrics(candles.get("_chain") or {}),
    }


def _chain_metrics(chain: dict) -> dict:
    """Derive usable signals from the full option chain (IV, OI, skew).

    chain: the underlying's chain dict from option_chains.json
           {spot, strikes: {"22600_CE": {iv, oi, delta, ...}, ...}}
    Returns {atm_iv, max_oi_call, max_oi_put, max_oi_strike, pcr_oi,
             call_iv, put_iv, skew} — None-safe.
    """
    out = {"atm_iv": None, "max_oi_call": None, "max_oi_put": None,
           "max_oi_strike": None, "pcr_oi": None, "call_iv": None,
           "put_iv": None, "skew": None, "n_strikes": 0}
    try:
        strikes = chain.get("strikes") or {}
        if not strikes:
            return out
        spot = float(chain.get("spot") or 0)
        calls, puts = {}, {}
        max_oi_call = max_oi_put = 0.0
        max_oi_strike = 0.0
        sum_call_iv = sum_put_iv = 0.0
        n_call = n_put = 0
        for key, s in strikes.items():
            try:
                strike = float(s.get("strike") or 0)
                opt = str(s.get("opt_type") or key.split("_")[-1]).upper()
                oi = float(s.get("oi") or 0)
                iv = float(s.get("iv") or 0)
            except Exception:
                continue
            if opt == "CE":
                calls[strike] = {"oi": oi, "iv": iv}
                sum_call_iv += iv; n_call += 1
                if oi > max_oi_call: max_oi_call = oi; max_oi_strike = strike
            elif opt == "PE":
                puts[strike] = {"oi": oi, "iv": iv}
                sum_put_iv += iv; n_put += 1
                if oi > max_oi_put: max_oi_put = oi
        out["n_strikes"] = len(strikes)
        if n_call and n_put:
            out["call_iv"] = sum_call_iv / n_call
            out["put_iv"] = sum_put_iv / n_put
            out["skew"] = out["put_iv"] - out["call_iv"]
            out["pcr_oi"] = max_oi_put / max_oi_call if max_oi_call > 0 else None
        out["max_oi_call"] = max_oi_call
        out["max_oi_put"] = max_oi_put
        out["max_oi_strike"] = max_oi_strike
        # ATM IV: nearest strike to spot
        if spot and calls or spot and puts:
            best = None
            for strike, s in {**calls, **puts}.items():
                if best is None or abs(strike - spot) < abs(best - spot):
                    best = strike
            if best is not None:
                out["atm_iv"] = (calls.get(best) or puts.get(best) or {}).get("iv")
    except Exception:
        pass
    return out


# ===== Setup scoring =====

def _score_iron_condor(r: dict) -> Optional[dict]:
    """Range-bound, low vol, no strong trend -> sell premium."""
    if r["direction"] != "range":
        return None
    if r["vol"] not in ("low", "elevated"):
        return None
    if r["trending"]:
        return None
    score = 50
    reasons = []
    if r["vol"] == "low":
        score += 20; reasons.append("low VIX favors premium sellers")
    if abs(r["session_pct"]) < 0.3:
        score += 15; reasons.append("tight range")
    if 40 <= r["rsi"] <= 60:
        score += 10; reasons.append("RSI neutral")
    if abs(r["vwap_dev"]) < 0.3:
        score += 5; reasons.append("price near VWAP")
    return {"structure": "iron_condor", "score": min(score, 100),
            "reasons": reasons, "direction": "neutral"}


def _score_vwap_bounce(r: dict) -> Optional[dict]:
    """Mean reversion: price stretched from VWAP snaps back."""
    dev = abs(r["vwap_dev"])
    if dev < 0.2:
        return None
    score = 40
    reasons = []
    if dev > 0.5:
        score += 25; reasons.append(f"extreme {r['vwap_dev']:+.2f}% from VWAP")
    elif dev > 0.3:
        score += 15; reasons.append(f"stretched {r['vwap_dev']:+.2f}% from VWAP")
    else:
        score += 5; reasons.append(f"mild {r['vwap_dev']:+.2f}% deviation")
    if not r["trending"]:
        score += 10; reasons.append("no strong trend (mean reversion works)")
    if 30 <= r["rsi"] <= 70:
        score += 5; reasons.append("RSI not extreme")
    direction = "long_call" if r["vwap_dev"] < 0 else "long_put"
    return {"structure": "vwap_bounce", "score": min(score, 100),
            "reasons": reasons, "direction": direction}


def _score_momentum(r: dict) -> Optional[dict]:
    """Trend continuation: EMA alignment + MACD + ADX confirm."""
    if not r["trending"]:
        return None
    score = 40
    reasons = []
    if r["ema_bull"] or r["ema_bear"]:
        score += 20; reasons.append("EMA9/21/50 aligned")
    if r["macd_bull"] or r["macd_bear"]:
        score += 15; reasons.append("MACD confirms")
    if r["adx"] > 30:
        score += 10; reasons.append(f"strong trend ADX={r['adx']:.0f}")
    if r["direction"] in ("bullish", "bearish"):
        score += 5; reasons.append(f"{r['direction']} regime")
    # Kronos foundation-model forecast confirms the trend direction
    kf = r.get("forecast") or {}
    if kf:
        if r["direction"] == "bullish" and kf.get("direction") == "UP":
            score += 15; reasons.append(f"Kronos forecasts UP ({kf.get('pct',0):+.2f}%)")
        elif r["direction"] == "bearish" and kf.get("direction") == "DOWN":
            score += 15; reasons.append(f"Kronos forecasts DOWN ({kf.get('pct',0):+.2f}%)")
        elif kf.get("direction"):
            score += 5; reasons.append("Kronos forecast present")
    # Research-backed candle patterns confirm the trend direction
    pat = r.get("patterns") or {}
    bull_pat = any(pat.get(k, 0) > 0 for k in
                   ("cdl_threewhitesoldiers", "cdl_morningstar", "cdl_piercing",
                    "cdl_hammer", "cdl_beltabhold"))
    bear_pat = any(pat.get(k, 0) < 0 for k in
                   ("cdl_threeblackcrows", "cdl_eveningstar", "cdl_darkcloudcover",
                    "cdl_shootingstar", "cdl_hangingman"))
    if r["direction"] == "bullish" and bull_pat:
        score += 15; reasons.append("bullish candle pattern confirms")
    elif r["direction"] == "bearish" and bear_pat:
        score += 15; reasons.append("bearish candle pattern confirms")
    elif bull_pat or bear_pat:
        score += 5; reasons.append("candle pattern present, trend pending")
    direction = "long_call" if r["direction"] == "bullish" else "long_put"
    return {"structure": "momentum", "score": min(score, 100),
            "reasons": reasons, "direction": direction}


def _score_rsi_extreme(r: dict) -> Optional[dict]:
    """RSI(2) extreme -> mean reversion (Connors)."""
    # RSI(2) from candles if available
    rsi2 = None
    # fall back to RSI-14 extreme
    if r["rsi"] < 25 or r["rsi"] > 75:
        score = 55
        direction = "long_call" if r["rsi"] < 25 else "long_put"
        reasons = [f"RSI-14 {r['rsi']:.0f} extreme"]
        if not r["trending"]:
            score += 15; reasons.append("no trend (reversion safe)")
        return {"structure": "rsi_reversion", "score": min(score, 100),
                "reasons": reasons, "direction": direction}
    return None


# ===== Leg building =====

def _build_legs(decision: dict, spot: float, vix: float, capital: float = 100000.0) -> list:
    """Build concrete option legs for the chosen structure.

    Returns a list of {side, qty, strike, opt_type, order_type, price}.
    Underlying-aware: lot_size + strike step come from the decision (set by
    the multi-underlying decide_all).
    """
    if not spot:
        return []
    underlying = decision.get("underlying") or "NIFTY"
    step = int(decision.get("strike_step") or STRIKE_STEPS.get(underlying, 50))
    lot_size = int(decision.get("lot_size") or LOT_SIZES.get(underlying, 75))
    atm = round(spot / step) * step  # NIFTY
    # Vol-targeted sizing: risk ~1% of capital per trade
    n_lots = max(1, int(capital * 0.01 / (spot * 0.005 * lot_size)))
    n_lots = min(n_lots, 10)
    target_leg_price = max(20, round(spot * 0.005))
    structure = decision.get("structure")
    direction = decision.get("direction")

    if structure == "iron_condor":
        ce_short = atm + 100
        ce_long = ce_short + 100
        pe_short = atm - 100
        pe_long = pe_short - 100
        return [
            {"side": "SELL", "qty": n_lots * lot_size, "strike": ce_short, "opt_type": "CE", "order_type": "LIMIT", "price": target_leg_price},
            {"side": "BUY", "qty": n_lots * lot_size, "strike": ce_long, "opt_type": "CE", "order_type": "LIMIT", "price": target_leg_price * 0.3},
            {"side": "SELL", "qty": n_lots * lot_size, "strike": pe_short, "opt_type": "PE", "order_type": "LIMIT", "price": target_leg_price},
            {"side": "BUY", "qty": n_lots * lot_size, "strike": pe_long, "opt_type": "PE", "order_type": "LIMIT", "price": target_leg_price * 0.3},
        ]
    if structure in ("momentum", "vwap_bounce", "rsi_reversion",
                    "trend_follow_simple", "breakout", "pullback_trend",
                    "range_fade"):
        opt_type = "CE" if direction == "long_call" else "PE"
        return [
            {"side": "BUY", "qty": n_lots * lot_size, "strike": atm, "opt_type": opt_type, "order_type": "MARKET", "price": None}
        ]
    if structure == "straddle":
        return [
            {"side": "BUY", "qty": n_lots * lot_size, "strike": atm, "opt_type": "CE", "order_type": "MARKET", "price": None},
            {"side": "BUY", "qty": n_lots * lot_size, "strike": atm, "opt_type": "PE", "order_type": "MARKET", "price": None},
        ]
    if structure == "strangle":
        return [
            {"side": "BUY", "qty": n_lots * lot_size, "strike": atm + 100, "opt_type": "CE", "order_type": "MARKET", "price": None},
            {"side": "BUY", "qty": n_lots * lot_size, "strike": atm - 100, "opt_type": "PE", "order_type": "MARKET", "price": None},
        ]
    if structure == "put_spread":
        short_strike = atm - 50
        long_strike = atm - 100
        return [
            {"side": "SELL", "qty": n_lots * lot_size, "strike": short_strike, "opt_type": "PE", "order_type": "LIMIT", "price": target_leg_price},
            {"side": "BUY", "qty": n_lots * lot_size, "strike": long_strike, "opt_type": "PE", "order_type": "LIMIT", "price": target_leg_price * 0.3},
        ]
    return []


def resolve_expiry(now=None) -> str:
    """Resolve the current weekly expiry (next Thursday) as YYYY-MM-DD.

    The SYSTEM owns expiry resolution — it computes the real date itself
    instead of passing a "WEEKLY" placeholder for the bridge to guess.
    NIFTY/BANKNIFTY weekly options expire on Thursday.
    """
    from datetime import date, timedelta
    today = (now or datetime.now()).date()
    days_ahead = (3 - today.weekday()) % 7  # Thursday=3
    if days_ahead == 0:
        days_ahead = 7  # today IS expiry Thursday -> next week
    exp = today + timedelta(days=days_ahead)
    return exp.strftime("%Y-%m-%d")


def build_plan(decision: dict, context: dict) -> dict:
    """Attach concrete legs + sizing to a decision. Returns a trade_plan dict.
    Underlying-aware: spot comes from the decision's underlying, not NIFTY."""
    und = decision.get("underlying") or "NIFTY"
    candles = context.get("candles") or {}
    n = (candles.get("symbols") or {}).get(und) or {}
    spot = float(n.get("ltp") or decision.get("spot") or 0)
    vix = float(context.get("vix") or 15)
    paper = context.get("paper") or {}
    capital = float(paper.get("cash") or 100000)
    legs = _build_legs(decision, spot, vix, capital)
    return {
        "strategy": decision.get("structure"),
        "structure": decision.get("structure"),
        "underlying": und,
        "n_lots": legs[0]["qty"] if legs else 1,
        "expiry": resolve_expiry(),
        "max_hold_minutes": 300,
        "rationale": decision.get("rationale", ""),
        "legs": legs,
        "edge_score": decision.get("edge_score", 0),
        "direction": decision.get("direction"),
    }


# ===== Position management =====

def manage_positions(positions: dict, regime: dict, capital: float = 100000.0,
                     peak_state: dict | None = None) -> dict:
    """Decide whether to CLOSE / HOLD / TRAIL open positions — LIVE management.

    Returns a decision dict. Rules (Option B — ride winning moves):
      - STOP: total P&L <= -2% of capital -> CLOSE (never let a loss grow)
      - TARGET: total P&L >= +1.5% of capital -> CLOSE (bank a solid win)
      - TRAIL: once P&L >= +0.5%, trail a stop at (peak - 0.8% of capital).
        This lets a winning position keep riding while guaranteeing we keep
        most of the profit if it reverses. This is the "capture the move,
        not just the first 1%" behaviour.
      - REGIME-BREAK: only closes 2+ leg NEUTRAL spreads (iron condor) when a
        trend breaks the range. Single directional legs ride the trend.
      - EOD: day-trade structures close at 15:20 IST.
      - Otherwise HOLD (multi-day).

    peak_state: {sym: peak_pnl} tracked by the operator so the trail survives
    across decide cycles (the projection itself doesn't store peaks).
    """
    if not positions:
        return {"action": "HOLD", "rationale": "no positions to manage"}

    # Dedupe positions by (strike, option_type) — the same leg can appear
    # twice with a truncated symbol (e.g. NIFTY22400PE == NIFTY29OCT2622400PE).
    deduped = {}
    for sym, pos in positions.items():
        key = (float(pos.get("strike") or 0), str(pos.get("option_type") or "").upper())
        if key in deduped:
            deduped[key]["qty"] = float(deduped[key].get("qty") or 0) + float(pos.get("qty") or 0)
        else:
            deduped[key] = dict(pos)

    # Compute per-leg and total P&L
    leg_pnl = {}
    total_pnl = 0.0
    for key, pos in deduped.items():
        qty = float(pos.get("qty") or 0)
        avg = float(pos.get("avg_price") or 0)
        ltp = float(pos.get("ltp") or avg)
        pnl = (ltp - avg) * qty if qty > 0 else (avg - ltp) * abs(qty)
        leg_pnl[key] = pnl
        total_pnl += pnl

    n_nonzero = len([p for p in positions.values() if float(p.get("qty") or 0) != 0])

    # Targets / stops as % of capital. Options need room to breathe:
    stop = -capital * 0.02        # -2% hard stop — cut before it grows
    trail_arm = capital * 0.005   # +0.5% -> trailing stop arms
    trail_gap = capital * 0.008   # trail 0.8% below the peak
    target = capital * 0.015      # +1.5% bank a solid win

    # ---- 1) Hard stop: never let a loss run ----
    if total_pnl <= stop:
        return {
            "action": "CLOSE", "symbol": "ALL", "qty": 0, "price": 0,
            "edge_score": 0,
            "rationale": f"stop hit: P&L {total_pnl:+,.0f} <= {stop:+,.0f} — cut loss, protect capital",
            "regime": regime,
        }

    # ---- 2) Track the peak for the trailing stop ----
    if peak_state is None:
        peak_state = {}
    for key in deduped:
        cur = leg_pnl.get(key, 0.0)
        peak_state[key] = max(float(peak_state.get(key, cur)), cur)

    # ---- 3) TARGET: bank a solid win ----
    if total_pnl >= target:
        return {
            "action": "CLOSE", "symbol": "ALL", "qty": 0, "price": 0,
            "edge_score": 100,
            "rationale": f"target hit: P&L {total_pnl:+,.0f} >= {target:+,.0f} — bank the win",
            "regime": regime,
        }

    # ---- 4) TRAILING STOP: ride winners, keep most of the profit ----
    worst_leg_drawdown = 0.0
    trailed_leg = None
    for key in deduped:
        cur = leg_pnl.get(key, 0.0)
        peak = float(peak_state.get(key) or cur)
        if peak >= trail_arm:
            dd = peak - cur
            if dd >= trail_gap:
                trailed_leg = key
                worst_leg_drawdown = dd
    if trailed_leg is not None:
        return {
            "action": "CLOSE", "symbol": "ALL", "qty": 0, "price": 0,
            "edge_score": 80,
            "rationale": f"trailing stop: leg {trailed_leg[0]}{trailed_leg[1]} fell {worst_leg_drawdown:+.0f} from peak {peak_state.get(trailed_leg,0):+.0f} — lock profit, ride next time",
            "regime": regime,
        }

    # ---- 5) EOD close for day-trade structures ----
    try:
        from datetime import datetime as _dt, time as _dtm, timezone as _tz
        now = _dt.now(_tz(_dt.timedelta(hours=5, minutes=30)))
        if _dtm(15, 20) <= now.time() <= _dtm(15, 30):
            return {
                "action": "CLOSE", "symbol": "ALL", "qty": 0, "price": 0,
                "edge_score": 50,
                "rationale": f"EOD close: P&L {total_pnl:+,.0f} at 15:20 — options decay overnight",
                "regime": regime,
            }
    except Exception:
        pass

    # ---- 6) Regime-break: only multi-leg NEUTRAL spreads close on trend ----
    if n_nonzero >= 2 and regime.get("trending") and regime.get("direction") in ("bullish", "bearish"):
        return {
            "action": "CLOSE", "symbol": "ALL", "qty": 0, "price": 0,
            "edge_score": 0,
            "rationale": f"regime broke: {regime['direction']} trend (ADX {regime.get('adx'):.0f}) — multi-leg neutral edge gone, close",
            "regime": regime,
        }

    # ---- 7) HOLD: let it work ----
    armed = [k for k in deduped if float(peak_state.get(k, 0)) >= trail_arm]
    trail_txt = f", trail armed on {len(armed)} leg(s)" if armed else ""
    return {
        "action": "HOLD", "symbol": None, "qty": 0, "price": 0,
        "edge_score": 0,
        "rationale": f"holding {len(positions)} legs — P&L {total_pnl:+,.0f} within stop/target{trail_txt}, edge persists",
        "regime": regime,
    }

def _market_open() -> bool:
    """NSE equity-derivatives hours: 09:15-15:30 IST, Mon-Fri."""
    try:
        import datetime as _dt
        now = _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=5, minutes=30)))
        if now.weekday() >= 5:
            return False
        t = now.time()
        return _dt.time(9, 15) <= t <= _dt.time(15, 30)
    except Exception:
        return False


def decide(context: dict) -> dict:
    """Return ONE decision: OPEN/CLOSE/HOLD with the best setup.

    context keys: candles (candles_aggregate dict), intraday, vix,
                  paper (positions), now, news (optional)
    """
    # HARD market-hours gate: never trade outside NSE hours
    if not _market_open():
        return {"action": "HOLD", "structure": "market-closed",
                "edge_score": 0, "rationale": "NSE closed - no trading outside 09:15-15:30 IST"}
    candles = context.get("candles") or {}
    intraday = context.get("intraday") or {}
    vix = float(context.get("vix") or 15)
    paper = context.get("paper") or {}
    positions = paper.get("positions") or {}
    now = context.get("now") or datetime.now()

    # If we have open positions, decide whether to HOLD overnight (multi-day
    # setup) or CLOSE at EOD. Multi-day-friendly structures (iron_condor,
    # momentum) can be carried if the edge persists; day-trade structures
    # (vwap_bounce, rsi_reversion) close at EOD.
    if positions:
        r = _regime(candles, intraday, vix)
        # Real position management: target/stop/edge-based exits.
        capital = float(paper.get("cash") or 100000)
        mgmt = manage_positions(positions, r, capital)
        return mgmt

    r = _regime(candles, intraday, vix)

    # Score EVERY strategy in the bible against the CURRENT regime, and take
    # the single best. This makes the engine regime-aware: trend-following
    # fires on a strong-trend day, mean-reversion in a range, premium-selling
    # in low vol, volatility plays when IV spikes — the right tool for the
    # market we're actually in.
    try:
        from strategy_bible import best_strategy
        best = best_strategy(r)
    except Exception:
        best = None

    if not best:
        return {
            "action": "HOLD", "structure": None, "symbol": None,
            "qty": 0, "price": 0, "edge_score": 0,
            "rationale": f"no setup has edge in {r['direction']}/{r['vol']} vol regime — preserve capital",
            "regime": r,
        }

    # Best-of-best: only if it clears the quality bar (>= 65). Otherwise HOLD
    # and preserve capital. Lower threshold than before (70) so genuine trend
    # setups aren't gated out, but still no forced trades.
    if best["score"] < 65:
        return {
            "action": "HOLD", "structure": None, "symbol": None,
            "qty": 0, "price": 0, "edge_score": best["score"],
            "rationale": f"best setup {best['structure']} edge {best['score']:.0f} < 70 bar — wait for better",
            "regime": r,
        }

    return {
        "action": "OPEN", "structure": best["structure"],
        "symbol": "NIFTY", "qty": 1, "price": 0,
        "edge_score": best["score"],
        "rationale": f"{best['structure']} edge {best['score']:.0f}/100 — {'; '.join(best['reasons'])}",
        "regime": r,
        "direction": best["direction"],
    }



# ===== Multi-underlying selection (the full market, not just NIFTY) =====

LOT_SIZES = {"NIFTY": 75, "BANKNIFTY": 30, "FINNIFTY": 65,
             "MIDCPNIFTY": 120, "SENSEX": 20}
STRIKE_STEPS = {"NIFTY": 50, "BANKNIFTY": 100, "FINNIFTY": 50,
                "MIDCPNIFTY": 50, "SENSEX": 100}


def _underlying_context(sym: str, candles: dict, intraday: dict, option_chains: dict) -> Optional[dict]:
    """Build a per-underlying context (candles + intraday + chain) so the
    strategy bible can score this index on its own. Returns None if no data."""
    n = (candles.get("symbols") or {}).get(sym) or {}
    ind = n.get("indicators") or {}
    spot = float(n.get("ltp") or 0)
    if not spot:
        return None
    id_sym = intraday.get(sym) if isinstance(intraday, dict) else None
    if not isinstance(id_sym, dict):
        id_sym = intraday
    chain = (option_chains.get("chains") or {}).get(sym) or {}
    return {
        "candles": {"symbols": {sym: n}},
        "intraday": id_sym,
        "vix": float((intraday.get("_vix") if isinstance(intraday, dict) else 0) or 15),
        "underlying": sym,
        "spot": spot,
        "indicators": ind,
        "chain": chain,
        "lot_size": LOT_SIZES.get(sym, 75),
        "strike_step": STRIKE_STEPS.get(sym, 50),
    }


def decide_all(context: dict) -> dict:
    """Score every strategy on EVERY live underlying, take the single best
    opportunity across the whole market. Returns a decision dict with the
    chosen underlying attached (under symbol as f"{UND}:{strike}:{opt}")."""
    import strategy_bible
    candles = context.get("candles") or {}
    intraday = context.get("intraday") or {}
    option_chains = context.get("option_chains") if isinstance(context.get("option_chains"), dict) else None
    # If chains not passed separately, reuse the live file already read
    if option_chains is None and isinstance(context, dict):
        option_chains = context.get("chains")
    if option_chains is None:
        try:
            option_chains = json.loads((DATA / "option_chains.json").read_text(encoding="utf-8"))
        except Exception:
            option_chains = {}
    chains = (option_chains.get("chains") or {}) if isinstance(option_chains, dict) else {}

    best_overall = None
    for sym in LOT_SIZES:
        ctx = _underlying_context(sym, candles, intraday, option_chains)
        if not ctx or not ctx["spot"]:
            continue
        r = _regime({**ctx["candles"], "_underlying": sym, "_chain": ctx.get("chain") or {}},
                    ctx["intraday"], ctx["vix"])
        r["spot"] = ctx["spot"]
        r["underlying"] = sym
        r["_bars"] = _read_candle_history(sym) if False else r.get("_bars")
        try:
            b = strategy_bible.best_strategy(r)
        except Exception:
            b = None
        if b:
            b["underlying"] = sym
            b["lot_size"] = ctx["lot_size"]
            b["strike_step"] = ctx["strike_step"]
            if not best_overall or b["score"] > best_overall["score"]:
                best_overall = b

    if not best_overall:
        return {"action": "HOLD", "structure": None, "symbol": None,
                "qty": 0, "price": 0, "edge_score": 0,
                "rationale": "no setup has edge in any live underlying — preserve capital",
                "regime": None}
    if best_overall["score"] < 65:
        return {"action": "HOLD", "structure": None, "symbol": None,
                "qty": 0, "price": 0, "edge_score": best_overall["score"],
                "rationale": f"best {best_overall['underlying']} {best_overall['structure']} edge {best_overall['score']:.0f} < 65 — wait",
                "regime": None}
    return {
        "action": "OPEN",
        "structure": best_overall["structure"],
        "underlying": best_overall["underlying"],
        "symbol": best_overall["underlying"],
        "direction": best_overall["direction"],
        "qty": 1, "price": 0,
        "edge_score": best_overall["score"],
        "lot_size": best_overall["lot_size"],
        "strike_step": best_overall["strike_step"],
        "rationale": f"{best_overall['underlying']} {best_overall['structure']} edge {best_overall['score']:.0f}/100 — {'; '.join(best_overall['reasons'])}",
    }
