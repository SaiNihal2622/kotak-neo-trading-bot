"""strategy_bible.py — Comprehensive regime-aware strategy library.

Instead of a handful of fixed templates with hardcoded thresholds, this
defines a FAMILY of distinct strategies, each declaring the market regime(s)
and conditions it thrives in. The decision engine scores ALL applicable
strategies for the CURRENT regime and takes the single best — so the system
automatically uses trend-following on a strong-trend day, mean-reversion in a
range, premium-selling in low vol, volatility plays when IV spikes, etc.

Each strategy is a dict:
    {
      name, family, bias (long/short/neutral),
      regime (list), structure (leg type), build (legs fn),
      score(r) -> (score, [reasons]) | None   # None = not applicable now
    }

The score(r) returns a 0-100 edge score. The engine picks the highest.
"""
from __future__ import annotations
import math
from typing import Optional, Dict, Any, List


def _kf_direction(r) -> Optional[str]:
    """Kronos forecast direction (UP/DOWN) or None."""
    kf = r.get("forecast") or {}
    return kf.get("direction")


def _kf_pct(r) -> float:
    kf = r.get("forecast") or {}
    return float(kf.get("pct") or 0)


# ---------------------------------------------------------------------------
# TREND-FOLLOWING strategies (the ones that capture strong moves like today's
# +207pt day — the engine had NONE that fired, which is why we missed it)
# ---------------------------------------------------------------------------

def _score_trend_follow(r) -> Optional[dict]:
    """Directional long/short riding the dominant trend. Fires on strong day."""
    if not r["trending"]:
        return None
    bull = r["direction"] == "bullish"
    bear = r["direction"] == "bearish"
    if not (bull or bear):
        return None
    score = 45
    reasons = []
    bias = "long_call" if bull else "long_put"
    lbl = "bullish" if bull else "bearish"
    # Trend strength
    if r["adx"] > 30:
        score += 15; reasons.append(f"strong trend ADX={r['adx']:.0f}")
    if r["ema_bull"] if bull else r["ema_bear"]:
        score += 10; reasons.append("EMA9/21/50 aligned")
    if r["macd_bull"] if bull else r["macd_bear"]:
        score += 10; reasons.append("MACD confirms")
    # Session move — today we want to ride it, not fade it
    if (bull and r["session_pct"] > 0.5) or (bear and r["session_pct"] < -0.5):
        score += 10; reasons.append(f"session {r['session_pct']:+.1f}% {lbl} momentum")
    # Kronos alignment
    if _kf_direction(r) == ("UP" if bull else "DOWN"):
        score += 15; reasons.append(f"Kronos confirms {lbl} ({_kf_pct(r):+.2f}%)")
    # Candle patterns
    pat = r.get("patterns") or {}
    if bull:
        if any(pat.get(k, 0) > 0 for k in ("cdl_threewhitesoldiers", "cdl_morningstar", "cdl_piercing", "cdl_marubozu")):
            score += 10; reasons.append("bullish candle pattern")
        if any(pat.get(k, 0) < 0 for k in ("cdl_threeblackcrows", "cdl_eveningstar")):
            score -= 15; reasons.append("bearish pattern conflicts")
    else:
        if any(pat.get(k, 0) < 0 for k in ("cdl_threeblackcrows", "cdl_eveningstar", "cdl_darkcloudcover", "cdl_marubozu")):
            score += 10; reasons.append("bearish candle pattern")
        if any(pat.get(k, 0) > 0 for k in ("cdl_threewhitesoldiers", "cdl_morningstar")):
            score -= 15; reasons.append("bullish pattern conflicts")
    return {"structure": "trend_follow_simple", "score": max(0, min(score, 100)),
            "reasons": reasons, "direction": bias}


def _score_breakout(r) -> Optional[dict]:
    """Breakout continuation: price at session high/low with volume expansion."""
    # Requires recent bar touching new high/low. Approximation:
    bars = r.get("_bars") or []
    if len(bars) < 10:
        return None
    n = r.get("direction")
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    last = bars[-1]
    at_high = last["high"] >= max(highs[-10:-1])
    at_low = last["low"] <= min(lows[-10:-1])
    if not (at_high or at_low):
        return None
    score = 40
    reasons = []
    bias = "long_call" if at_high and not at_low else "long_put"
    if at_high and n == "bullish":
        score += 25; reasons.append("breakout to new session high in uptrend")
    elif at_low and n == "bearish":
        score += 25; reasons.append("breakdown to new session low in downtrend")
    else:
        score += 10; reasons.append("range breakout, direction unclear")
    if r["vol"] == "low":
        score += 10; reasons.append("tight range precedes breakout")
    if _kf_direction(r):
        score += 10; reasons.append("Kronos forecast present")
    return {"structure": "breakout", "score": min(score, 100),
            "reasons": reasons, "direction": bias}


def _score_pullback(r) -> Optional[dict]:
    """Buy the dip / sell the rip in an intact trend (trend-respect re-entry)."""
    if not r["trending"]:
        return None
    bull = r["direction"] == "bullish"
    bear = r["direction"] == "bearish"
    if not (bull or bear):
        return None
    # Price pulled back toward VWAP/EMA21 but trend intact
    dev = r["vwap_dev"]
    into_trend = (bull and dev < 0) or (bear and dev > 0)
    if not into_trend:
        return None
    score = 45
    reasons = []
    bias = "long_call" if bull else "long_put"
    if r["adx"] > 28:
        score += 15; reasons.append("trend strong (pullback re-entry)")
    if (bull and 45 <= r["rsi"] <= 60) or (bear and 40 <= r["rsi"] <= 55):
        score += 15; reasons.append("RSI pullback zone")
    if _kf_direction(r) == ("UP" if bull else "DOWN"):
        score += 15; reasons.append("Kronos confirms trend")
    return {"structure": "pullback_trend", "score": min(score, 100),
            "reasons": reasons, "direction": bias}


# ---------------------------------------------------------------------------
# MEAN REVERSION / RANGE strategies
# ---------------------------------------------------------------------------

def _score_iron_condor(r) -> Optional[dict]:
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
    return {"structure": "iron_condor", "score": min(score, 100),
            "reasons": reasons, "direction": "neutral"}


def _score_vwap_bounce(r) -> Optional[dict]:
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
    direction = "long_call" if r["vwap_dev"] < 0 else "long_put"
    return {"structure": "vwap_bounce", "score": min(score, 100),
            "reasons": reasons, "direction": direction}


def _score_rsi_extreme(r) -> Optional[dict]:
    if r["rsi"] < 25 or r["rsi"] > 75:
        score = 55
        direction = "long_call" if r["rsi"] < 25 else "long_put"
        reasons = [f"RSI-14 {r['rsi']:.0f} extreme"]
        if not r["trending"]:
            score += 15; reasons.append("no trend (reversion safe)")
        return {"structure": "rsi_reversion", "score": min(score, 100),
                "reasons": reasons, "direction": direction}
    return None


def _score_range_fade(r) -> Optional[dict]:
    """Fade the edges of an established sideways band (support/resistance)."""
    if r["direction"] != "range":
        return None
    # price near session high -> short side; near low -> long side
    bars = r.get("_bars") or []
    if len(bars) < 5:
        return None
    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]
    hi = max(highs); lo = min(lows)
    if hi - lo <= 0:
        return None
    pos = (r["spot"] - lo) / (hi - lo)
    if pos > 0.85:
        score = 55; direction = "long_put"; reasons = ["price at range top — fade down", f"zone pos {pos:.2f}"]
    elif pos < 0.15:
        score = 55; direction = "long_call"; reasons = ["price at range bottom — fade up", f"zone pos {pos:.2f}"]
    else:
        return None
    if r["vol"] == "low":
        score += 15; reasons.append("low vol — clean range")
    if _kf_direction(r):
        score += 10; reasons.append("Kronos forecast present")
    return {"structure": "range_fade", "score": min(score, 100),
            "reasons": reasons, "direction": direction}


# ---------------------------------------------------------------------------
# VOLATILITY strategies
# ---------------------------------------------------------------------------

def _score_straddle(r) -> Optional[dict]:
    """Long volatility — buy both sides when IV compressed but move expected."""
    # Fires when VIX/elevated + neutral but with elevated ATR/session expanding
    if r["vol"] not in ("elevated", "high"):
        return None
    if not r["trending"] and abs(r["session_pct"]) < 0.3:
        # compressed vol building (coiling) — good for a straddle
        score = 50
        reasons = ["IV elevated, price coiling (volatility expansion play)"]
        if r["vol"] == "high":
            score -= 10; reasons.append("already high vol — premium costly")
        else:
            score += 10; reasons.append("elevated not extreme — cheap enough")
        if _kf_pct(r) > 0.05 or _kf_pct(r) < -0.05:
            score += 15; reasons.append("Kronos expects a move")
        return {"structure": "straddle", "score": min(score, 100),
                "reasons": reasons, "direction": "both"}
    return None


def _score_strangle(r) -> Optional[dict]:
    """Long out-of-the-money volatility (cheaper than straddle, needs bigger move)."""
    if r["vol"] not in ("elevated", "high"):
        return None
    if not r["trending"] and abs(r["session_pct"]) < 0.4:
        score = 45
        reasons = ["IV elevated, no trend — OTM strangle for expansion"]
        if _kf_pct(r) > 0.08 or _kf_pct(r) < -0.08:
            score += 20; reasons.append("Kronos expects a sizeable move")
        return {"structure": "strangle", "score": min(score, 100),
                "reasons": reasons, "direction": "both"}
    return None


# ---------------------------------------------------------------------------
# BREAKDOWN / crisis strategies (defensive income in a crash)
# ---------------------------------------------------------------------------

def _score_put_spread(r) -> Optional[dict]:
    """Bearish credit spread — collect premium on a muted/down day."""
    if r["direction"] != "bearish":
        return None
    score = 45
    reasons = [f"bearish regime ({r['direction']}) — sell put spread"]
    if r["adx"] > 30:
        score += 15; reasons.append(f"strong down ADX={r['adx']:.0f}")
    if _kf_direction(r) == "DOWN":
        score += 20; reasons.append(f"Kronos confirms down ({_kf_pct(r):+.2f}%)")
    if r["self_rsi"] if False else (r["rsi"] < 40):
        score += 10; reasons.append("undersold but trending down")
    return {"structure": "put_spread", "score": min(score, 100),
            "reasons": reasons, "direction": "long_put"}


# ---------------------------------------------------------------------------
# Registry: every strategy the engine may consider, with its bias + structure
# ---------------------------------------------------------------------------
STRATEGIES: List[Dict[str, Any]] = [
    {"name": "Trend Follow", "family": "trend", "bias": "directional",
     "structure": "trend_follow_simple", "score_fn": _score_trend_follow},
    {"name": "Breakout", "family": "trend", "bias": "directional",
     "structure": "breakout", "score_fn": _score_breakout},
    {"name": "Trend Pullback", "family": "trend", "bias": "directional",
     "structure": "pullback_trend", "score_fn": _score_pullback},
    {"name": "Iron Condor", "family": "range", "bias": "neutral",
     "structure": "iron_condor", "score_fn": _score_iron_condor},
    {"name": "Range Fade", "family": "range", "bias": "directional",
     "structure": "range_fade", "score_fn": _score_range_fade},
    {"name": "VWAP Bounce", "family": "reversion", "bias": "directional",
     "structure": "vwap_bounce", "score_fn": _score_vwap_bounce},
    {"name": "RSI Extreme Reversion", "family": "reversion", "bias": "directional",
     "structure": "rsi_reversion", "score_fn": _score_rsi_extreme},
    {"name": "Straddle", "family": "volatility", "bias": "both",
     "structure": "straddle", "score_fn": _score_straddle},
    {"name": "Strangle", "family": "volatility", "bias": "both",
     "structure": "strangle", "score_fn": _score_strangle},
    {"name": "Bear Put Spread", "family": "defensive", "bias": "long_put",
     "structure": "put_spread", "score_fn": _score_put_spread},
]


def score_all(r: dict) -> List[dict]:
    """Score every strategy against the current regime. Returns list of hits."""
    out = []
    for s in STRATEGIES:
        try:
            res = s["score_fn"](r)
            if res:
                res["name"] = s["name"]
                res["family"] = s["family"]
                out.append(res)
        except Exception:
            continue
    return out


def best_strategy(r: dict) -> Optional[dict]:
    """Return the single highest-scoring applicable strategy (or None)."""
    hits = score_all(r)
    if not hits:
        return None
    return max(hits, key=lambda c: c["score"])
