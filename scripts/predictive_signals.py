"""predictive_signals.py — simple statistical predictive signals for the brain.

FIX 2026-09-08 22:50: the brain has no forward-looking signal. It reacts
to events but doesn't predict. This module adds 6 statistical signals
that are computed from the existing 1m candles (no ML needed) and
written to data_cache/predictive_signals.json for the brain's context.

The signals are intentionally simple, interpretable, and rule-based
(no neural network, no sklearn, no external model). The brain still
makes the final decision; these are inputs to its reasoning.

Signal 1: MOMENTUM_1H
  - Score = sign of return over last 60 minutes, weighted by recent vs older.
  - Range: -1.0 to +1.0
  - Heuristic: strong recent momentum = continuation bias.

Signal 2: VOLATILITY_REGIME
  - Score = current 1h realized vol vs 20-bar average
  - Range: 0.0 to 2.0+ (1.0 = normal, >1.5 = high vol regime)
  - Heuristic: high vol = wider stops, smaller size, more gamma plays.

Signal 3: TREND_STRENGTH
  - Score = abs(20-bar slope) / 20-bar stdev
  - Range: 0.0 to 5.0+ (>2 = strong trend, <0.5 = range)
  - Heuristic: high slope/stdev = trend day, mean-reversion trades lose.

Signal 4: MEAN_REVERSION_PROB
  - Score = how many std-devs the last 1h return is from 0
  - Range: 0.0 to 4.0+ (>2.0 = likely to revert, <0.5 = trending)
  - Heuristic: extreme moves tend to revert (half-life ~1-4h).

Signal 5: RSI_14
  - Score = 14-bar Wilder RSI on 1m candles
  - Range: 0 to 100 (<30 oversold, >70 overbought)
  - Heuristic: mean-reversion at extremes, trend at mid-range.

Signal 6: PATTERN_BREAKOUT
  - Score = current price vs 20-bar high/low channel
  - Range: 0.0 to 1.0 (1.0 = at 20-bar high = breakout up)
  - Heuristic: breakouts above 20-bar high often continue; below 20-bar low often continue down.

Output: data_cache/predictive_signals.json — read by the brain's watch_loop.
Updated every 1 minute by the brain's candle refresh cycle.
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
DCACHE = ROOT / "data_cache"
OUT = DCACHE / "predictive_signals.json"


def _load_candles(symbol: str = "NIFTY", interval: str = "1m", lookback: int = 240) -> list[dict]:
    """Load recent candles from data_cache/candles/{symbol}_{interval}.json.
    The candle engine writes these every 60s during market hours.
    Returns list of {ts, open, high, low, close, volume} sorted oldest first.
    """
    p = DCACHE / "candles" / f"{symbol}_{interval}.json"
    if not p.exists():
        return []
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        candles = d.get("candles", d) if isinstance(d, dict) else d
        if not isinstance(candles, list):
            return []
        return candles[-lookback:]
    except Exception:
        return []


def _safe(xs: list, i: int) -> float:
    try:
        v = xs[i]
        if isinstance(v, dict):
            return float(v.get("close", 0) or 0)
        return float(v)
    except Exception:
        return 0.0


def _returns(closes: list[float]) -> list[float]:
    return [closes[i] - closes[i - 1] for i in range(1, len(closes)) if closes[i - 1] != 0]


def _stdev(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    v = sum((x - m) ** 2 for x in xs) / max(1, len(xs) - 1)
    return math.sqrt(v)


def _momentum_score(closes: list[float], window: int = 60) -> float:
    """Score = sign(weighted return) where recent bars get higher weight."""
    if len(closes) < window + 1:
        return 0.0
    rets = _returns(closes[-window - 1:])
    if not rets:
        return 0.0
    weights = [(i + 1) / len(rets) for i in range(len(rets))]  # 0..1, recent = high
    weighted = sum(w * r for w, r in zip(weights, rets))
    total_w = sum(weights)
    if total_w == 0:
        return 0.0
    avg = weighted / total_w
    return max(-1.0, min(1.0, avg / max(abs(_safe(closes, -1) - _safe(closes, -window - 1)) * 0.01, 0.01)))


def _volatility_regime(closes: list[float], vol_window: int = 60, baseline: int = 240) -> float:
    """Score = current 1h realized vol (stddev of 1m returns) / 20-bar average vol."""
    if len(closes) < baseline + 1:
        return 1.0
    rets_full = _returns(closes[-baseline - 1:])
    if len(rets_full) < vol_window + 1:
        return 1.0
    cur_vol = _stdev(rets_full[-vol_window:])
    base_vol = _stdev(rets_full)
    if base_vol <= 0:
        return 1.0
    return cur_vol / base_vol


def _trend_strength(closes: list[float], window: int = 20) -> float:
    """Score = abs(linear slope) / stdev. Higher = stronger trend."""
    if len(closes) < window + 1:
        return 0.0
    c = closes[-window - 1:]
    n = len(c)
    if n < 2:
        return 0.0
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(c) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, c))
    den = sum((x - mean_x) ** 2 for x in xs)
    if den == 0:
        return 0.0
    slope = num / den
    sd = _stdev(c)
    if sd == 0:
        return 0.0
    # normalize so 1% per bar = 1.0 (rough)
    return abs(slope) / sd * n


def _mean_reversion_prob(closes: list[float], window: int = 60) -> float:
    """Score = how many stddevs the last 1h return is from 0.
    Higher = more likely to revert (extreme move)."""
    if len(closes) < window + 1:
        return 0.0
    rets = _returns(closes[-window - 1:])
    last_ret = rets[-1] if rets else 0
    sd = _stdev(rets)
    if sd == 0:
        return 0.0
    return abs(last_ret) / sd


def _rsi_14(closes: list[float], period: int = 14) -> float:
    """Wilder's RSI on the last `period` returns."""
    if len(closes) < period + 1:
        return 50.0
    rets = _returns(closes[-(period + 1):])
    if not rets:
        return 50.0
    gains = [max(0, r) for r in rets]
    losses = [-min(0, r) for r in rets]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _pattern_breakout(closes: list[float], window: int = 20) -> dict:
    """Score = current price position within 20-bar high/low channel.
    1.0 = at 20-bar high (breakout up), 0.0 = at 20-bar low (breakout down)."""
    if len(closes) < window + 1:
        return {"position": 0.5, "breakout_up": False, "breakout_down": False}
    c = closes[-window - 1:]
    hi = max(c)
    lo = min(c)
    cur = c[-1]
    if hi == lo:
        return {"position": 0.5, "breakout_up": False, "breakout_down": False}
    pos = (cur - lo) / (hi - lo)
    return {
        "position": round(pos, 3),
        "breakout_up": pos > 0.95,
        "breakout_down": pos < 0.05,
    }


def _read_parquet_or_json(symbol: str, interval: str = "1m") -> list[dict]:
    """Try parquet first (the candle engine writes parquet), fall back to JSON,
    then to JSONL (the actual format used by the candle engine)."""
    p = DCACHE / "candles" / f"{symbol}_{interval}.parquet"
    if p.exists():
        try:
            import pandas as pd
            df = pd.read_parquet(p)
            return [
                {"ts": str(r.get("ts", "")), "open": float(r.get("open", 0)),
                 "high": float(r.get("high", 0)), "low": float(r.get("low", 0)),
                 "close": float(r.get("close", 0)), "volume": float(r.get("volume", 0))}
                for _, r in df.iterrows()
            ]
        except Exception:
            pass
    # FIX 2026-09-09 12:40: candle engine writes JSONL (not JSON). Each line is
    # {"epoch": ..., "ts": ..., "o": ..., "h": ..., "l": ..., "c": ..., "v": ...}
    jsonl = DCACHE / "candles" / f"{symbol}_{interval}.jsonl"
    if jsonl.exists():
        try:
            candles = []
            for line in jsonl.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    # Map JSONL fields to expected schema
                    candles.append({
                        "ts": d.get("ts", ""),
                        "open": float(d.get("o", 0) or 0),
                        "high": float(d.get("h", 0) or 0),
                        "low": float(d.get("l", 0) or 0),
                        "close": float(d.get("c", 0) or 0),
                        "volume": float(d.get("v", 0) or 0),
                    })
                except Exception:
                    continue
            if candles:
                return candles
        except Exception:
            pass
    return _load_candles(symbol, interval)


def _closes_from_candles(candles: list[dict]) -> list[float]:
    return [float(c.get("close", 0) or 0) for c in candles if c.get("close") is not None]


def compute_signals_for_symbol(symbol: str, interval: str = "1m") -> dict:
    """Compute all 6 signals for a single symbol."""
    candles = _read_parquet_or_json(symbol, interval)
    if len(candles) < 30:
        return {
            "symbol": symbol,
            "interval": interval,
            "n_candles": len(candles),
            "error": "insufficient data (<30 candles)",
        }
    closes = _closes_from_candles(candles)
    signals = {
        "symbol": symbol,
        "interval": interval,
        "n_candles": len(candles),
        "MOMENTUM_1H": _momentum_score(closes, 60),
        "VOLATILITY_REGIME": _volatility_regime(closes, 60, 240),
        "TREND_STRENGTH": _trend_strength(closes, 20),
        "MEAN_REVERSION_PROB": _mean_reversion_prob(closes, 60),
        "RSI_14": _rsi_14(closes, 14),
    }
    pb = _pattern_breakout(closes, 20)
    signals["PATTERN_BREAKOUT_position"] = pb["position"]
    signals["PATTERN_BREAKOUT_up"] = pb["breakout_up"]
    signals["PATTERN_BREAKOUT_down"] = pb["breakout_down"]

    # Composite score: simple weighted average of normalized signals
    # - momentum: high if strong
    # - trend_strength: high = trend day
    # - rsi: <30 = bullish, >70 = bearish (inverse)
    # - mean_reversion_prob: high = likely to revert (so inverse momentum bias)
    # - pattern: 0.5 = neutral, >0.95 = bullish breakout, <0.05 = bearish
    mom = max(-1, min(1, signals["MOMENTUM_1H"]))
    trend = min(2.0, signals["TREND_STRENGTH"]) / 2.0  # normalize 0..1
    rsi_inv = (50 - signals["RSI_14"]) / 50  # positive = oversold = bullish
    rsi_inv = max(-1, min(1, rsi_inv))
    pb_pos = (signals["PATTERN_BREAKOUT_position"] - 0.5) * 2  # -1..+1
    composite = (mom * 0.4 + trend * 0.2 + rsi_inv * 0.2 + pb_pos * 0.2)
    signals["COMPOSITE_SCORE"] = round(composite, 3)
    # Signal direction: -1 (bearish), 0 (neutral), +1 (bullish)
    if composite > 0.15:
        signals["DIRECTION"] = "BULLISH"
    elif composite < -0.15:
        signals["DIRECTION"] = "BEARISH"
    else:
        signals["DIRECTION"] = "NEUTRAL"
    # Confidence: 0..1 based on how strong the signal is
    signals["CONFIDENCE"] = round(min(1.0, abs(composite) * 1.5), 3)
    return signals


def main() -> int:
    t0 = time.time()
    out = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "duration_sec": 0.0,
        "symbols": {},
    }
    symbols = ("NIFTY", "BANKNIFTY")
    for sym in symbols:
        try:
            out["symbols"][sym] = compute_signals_for_symbol(sym, "1m")
        except Exception as e:
            out["symbols"][sym] = {"symbol": sym, "error": str(e)[:200]}
    out["duration_sec"] = round(time.time() - t0, 3)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    n_ok = sum(1 for s in out["symbols"].values() if "error" not in s)
    print(f"[predictive_signals] {n_ok}/{len(symbols)} symbols, {time.time()-t0:.2f}s")
    for sym, s in out["symbols"].items():
        if "error" in s:
            print(f"  {sym}: {s['error']}")
        else:
            print(f"  {sym}: direction={s['DIRECTION']} confidence={s['CONFIDENCE']:.2f} composite={s['COMPOSITE_SCORE']:+.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
