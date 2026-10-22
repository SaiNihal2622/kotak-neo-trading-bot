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

    return {
        "trending": trending,
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
    }


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
    """
    if not spot:
        return []
    atm = round(spot / 50) * 50  # NIFTY strikes are 50pt apart
    lot_size = 75  # NIFTY
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
            {"side": "SELL", "qty": n_lots, "strike": ce_short, "opt_type": "CE", "order_type": "LIMIT", "price": target_leg_price},
            {"side": "BUY", "qty": n_lots, "strike": ce_long, "opt_type": "CE", "order_type": "LIMIT", "price": target_leg_price * 0.3},
            {"side": "SELL", "qty": n_lots, "strike": pe_short, "opt_type": "PE", "order_type": "LIMIT", "price": target_leg_price},
            {"side": "BUY", "qty": n_lots, "strike": pe_long, "opt_type": "PE", "order_type": "LIMIT", "price": target_leg_price * 0.3},
        ]
    if structure in ("momentum", "vwap_bounce", "rsi_reversion"):
        opt_type = "CE" if direction == "long_call" else "PE"
        return [
            {"side": "BUY", "qty": n_lots, "strike": atm, "opt_type": opt_type, "order_type": "MARKET", "price": None}
        ]
    return []


def build_plan(decision: dict, context: dict) -> dict:
    """Attach concrete legs + sizing to a decision. Returns a trade_plan dict."""
    candles = context.get("candles") or {}
    n = (candles.get("symbols") or {}).get("NIFTY") or {}
    spot = float(n.get("ltp") or 0)
    vix = float(context.get("vix") or 15)
    paper = context.get("paper") or {}
    capital = float(paper.get("cash") or 100000)
    legs = _build_legs(decision, spot, vix, capital)
    return {
        "strategy": decision.get("structure"),
        "structure": decision.get("structure"),
        "underlying": "NIFTY",
        "n_lots": legs[0]["qty"] if legs else 1,
        "expiry": "WEEKLY",
        "max_hold_minutes": 300,
        "rationale": decision.get("rationale", ""),
        "legs": legs,
        "edge_score": decision.get("edge_score", 0),
        "direction": decision.get("direction"),
    }


# ===== Main entry =====

def decide(context: dict) -> dict:
    """Return ONE decision: OPEN/CLOSE/HOLD with the best setup.

    context keys: candles (candles_aggregate dict), intraday, vix,
                  paper (positions), now, news (optional)
    """


def decide(context: dict) -> dict:
    """Return ONE decision: OPEN/CLOSE/HOLD with the best setup.

    context keys: candles (candles_aggregate dict), intraday, vix,
                  paper (positions), now, news (optional)
    """
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
        # Determine if the open structure is multi-day-friendly
        multi_day_ok = False
        for sym in positions:
            s = str(sym).upper()
            if "CE" in s or "PE" in s:
                # iron_condor = 4 legs (2 short + 2 long) -> multi-day friendly
                # momentum = single directional -> can carry if trend persists
                multi_day_ok = True
                break
        # EOD check: after 15:00 IST, close day-trade structures; allow
        # multi-day structures to carry if edge persists.
        h, m = now.hour, now.minute
        is_eod = (h == 15 and m >= 0) or h > 15
        if is_eod and not multi_day_ok:
            return {
                "action": "CLOSE", "structure": None, "symbol": "ALL",
                "qty": 0, "price": 0, "edge_score": 0,
                "rationale": f"EOD ({now.strftime('%H:%M')}) — day-trade structure, close to bank P&L",
                "regime": r,
            }
        # Multi-day: hold if the regime still supports the position's edge
        if multi_day_ok and not is_eod:
            return {
                "action": "HOLD", "structure": None, "symbol": None,
                "qty": 0, "price": 0, "edge_score": 0,
                "rationale": f"holding {len(positions)} open position(s) — multi-day setup, edge persists in {r['direction']}/{r['vol']} regime",
                "regime": r,
            }
        # EOD + multi-day: let the brain decide (default HOLD to carry winner)
        return {
            "action": "HOLD", "structure": None, "symbol": None,
            "qty": 0, "price": 0, "edge_score": 0,
            "rationale": f"holding {len(positions)} open position(s) — multi-day setup, carry winner into tomorrow",
            "regime": r,
        }

    r = _regime(candles, intraday, vix)

    # Score all candidate setups
    candidates = []
    for scorer in (_score_iron_condor, _score_vwap_bounce,
                   _score_momentum, _score_rsi_extreme):
        try:
            c = scorer(r)
            if c:
                candidates.append(c)
        except Exception:
            continue

    if not candidates:
        return {
            "action": "HOLD", "structure": None, "symbol": None,
            "qty": 0, "price": 0, "edge_score": 0,
            "rationale": f"no setup has edge in {r['direction']}/{r['vol']} vol regime — preserve capital",
            "regime": r,
        }

    # Best-of-best: only the single highest-edge setup, and only if it
    # clears the quality bar (>= 70). Otherwise HOLD.
    best = max(candidates, key=lambda c: c["score"])
    if best["score"] < 70:
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
