"""Signal history — empirical win rates from real market data.

PHASE 7 FIX 2026-10-01: replaces hand-tuned thresholds with data-driven
statistics. The brain now uses REAL historical NIFTY data (yfinance)
to compute:

1. **Empirical win rate per signal combination**: when ADX>0.25 AND
   RSI>60 AND VWAP_dist>0.10%, what % of the time did NIFTY actually
   go up next day? (vs. down)

3. **Average gain/loss per signal**: not just win rate, but expected
   value (win_rate * avg_gain - (1-win_rate) * avg_loss)

3. **Volatility regime context**: realized vol vs typical → confidence

4. **Best threshold combination**: which (ADX, RSI, VWAP) combo has
   the highest Sharpe ratio historically?

This is the difference between TEMPLATE (hand-coded rules) and INTELLIGENT
(data-driven decisions). The brain prompt now contains these stats:
"Historically when ADX>0.25 + RSI>60 + VWAP_dist>0.10%, NIFTY was up
next day 70% of the time with avg gain +0.45% (Sharpe 1.2)."

The thresholds themselves become ADAPTIVE — they get re-tuned every
time the brain has accumulated 50+ new trade outcomes.
"""

from __future__ import annotations

import json
import math
import os
import statistics
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data_cache"
SIGNAL_HISTORY_FILE = DATA_DIR / "signal_history.json"

IST = timezone(timedelta(hours=5, minutes=30))

# Cache for yfinance data (avoid re-downloading every cycle)
NIFTY_CACHE = DATA_DIR / "nifty_daily_cache.json"
CACHE_TTL_SEC = 6 * 3600  # refresh every 6h


def _now_ist() -> datetime:
    return datetime.now(IST)


def fetch_nifty_daily(lookback_days: int = 365) -> list[dict]:
    """Fetch NIFTY daily OHLCV from yfinance. Cache for 6h.

    Returns list of {date, open, high, low, close, volume} dicts.
    On failure (no network, no yfinance), returns empty list.
    """
    if NIFTY_CACHE.exists():
        try:
            cache = json.loads(NIFTY_CACHE.read_text(encoding="utf-8"))
            if (datetime.now() - datetime.fromisoformat(cache["fetched_at"])).total_seconds() < CACHE_TTL_SEC:
                return cache.get("data", [])
        except Exception:
            pass

    try:
        import yfinance as yf
        import pandas as pd
        ticker = yf.Ticker("^NSEI")
        end = _now_ist()
        start = end - timedelta(days=lookback_days)
        hist = ticker.history(start=start.strftime("%Y-%m-%d"),
                              end=end.strftime("%Y-%m-%d"))
        if hist.empty:
            return []
        data = []
        for idx, row in hist.iterrows():
            data.append({
                "date": idx.strftime("%Y-%m-%d"),
                "open": float(row["Open"]),
                "high": float(row["High"]),
                "low": float(row["Low"]),
                "close": float(row["Close"]),
                "volume": int(row.get("Volume", 0) or 0),
            })
        # Cache
        NIFTY_CACHE.write_text(
            json.dumps({"fetched_at": _now_ist().isoformat(), "data": data}, indent=2),
            encoding="utf-8",
        )
        return data
    except Exception as e:
        print(f"[signal_history] yfinance fetch failed: {e}", file=sys.stderr)
        return []


def _nifty_daily_features(data: list[dict]) -> list[dict]:
    """For each day, compute proxies of ADX (5d range) and RSI (14d momentum).

    Returns enriched list with derived features:
        - daily_return: close-to-close % change
        - range_pct: (high - low) / close (proxy for intraday volatility)
        - trend_5d: 5-day close trend (% change)
        - rsi_14d: 14d RSI proxy (0..100)
        - adx_proxy: 5-day range as trend strength
    """
    if not data:
        return []
    enriched = []
    for i, day in enumerate(data):
        rec = dict(day)
        # Daily return
        if i > 0:
            prev = data[i - 1]["close"]
            if prev > 0:
                rec["daily_return"] = (day["close"] - prev) / prev * 100
            else:
                rec["daily_return"] = 0.0
        else:
            rec["daily_return"] = 0.0
        # Range %
        rec["range_pct"] = ((day["high"] - day["low"]) / day["close"] * 100) if day["close"] > 0 else 0.0
        # Trend over last 5 days
        if i >= 5:
            past = data[i - 5]["close"]
            rec["trend_5d"] = ((day["close"] - past) / past * 100) if past > 0 else 0.0
        else:
            rec["trend_5d"] = 0.0
        # 14-day RSI proxy
        if i >= 14:
            gains = []
            losses = []
            for j in range(i - 14, i):
                d = data[j + 1]["close"] - data[j]["close"]
                if d > 0:
                    gains.append(d)
                else:
                    losses.append(-d)
            avg_gain = statistics.mean(gains) if gains else 0
            avg_loss = statistics.mean(losses) if losses else 0.0001
            rs = avg_gain / avg_loss if avg_loss > 0 else 100
            rec["rsi_14d"] = 100 - (100 / (1 + rs))
        else:
            rec["rsi_14d"] = 50.0
        # ADX proxy: 5-day avg range / price
        if i >= 5:
            avg_range = statistics.mean([(data[j]["high"] - data[j]["low"]) / data[j]["close"] * 100 for j in range(i - 5, i) if data[j]["close"] > 0])
            rec["adx_proxy"] = avg_range * 10  # scale to look like ADX (5-30 range)
        else:
            rec["adx_proxy"] = 0.0
        enriched.append(rec)
    return enriched


def empirical_signal_stats(
    nifty_data: list[dict],
    *,
    adx_thresh: float = 0.25,
    rsi_long_thresh: float = 60,
    rsi_short_thresh: float = 40,
    forward_days: int = 1,
) -> dict:
    """Compute empirical win rate + avg gain for the current signal combination.

    Looks at all historical days where the signal combination matched, and
    measures forward-N-day returns. Returns stats for both long and short.
    """
    enriched = _nifty_daily_features(nifty_data)
    if not enriched:
        return {"error": "no data"}

    long_matches = []
    short_matches = []
    for i in range(len(enriched) - forward_days):
        rec = enriched[i]
        # Multi-signal filter (matches brain_daemon's logic)
        if rec["adx_proxy"] > adx_thresh and rec["rsi_14d"] > rsi_long_thresh and rec["trend_5d"] > 0.10:
            forward = enriched[i + forward_days]["close"]
            ret = (forward - rec["close"]) / rec["close"] * 100
            long_matches.append(ret)
        elif rec["adx_proxy"] > adx_thresh and rec["rsi_14d"] < rsi_short_thresh and rec["trend_5d"] < -0.10:
            forward = enriched[i + forward_days]["close"]
            ret = (rec["close"] - forward) / rec["close"] * 100  # short: profit when price falls
            short_matches.append(ret)

    def _stats(matches):
        if not matches:
            return {"n": 0, "win_rate": None, "avg_return": None, "sharpe": None, "max_gain": None, "max_loss": None}
        wins = [m for m in matches if m > 0]
        win_rate = len(wins) / len(matches) * 100
        avg = statistics.mean(matches)
        std = statistics.stdev(matches) if len(matches) > 1 else 0
        sharpe = (avg / std * math.sqrt(252 / forward_days)) if std > 0 else None
        return {
            "n": len(matches),
            "win_rate": round(win_rate, 1),
            "avg_return": round(avg, 3),
            "sharpe": round(sharpe, 2) if sharpe is not None else None,
            "max_gain": round(max(matches), 2),
            "max_loss": round(min(matches), 2),
        }

    return {
        "lookback_days": len(nifty_data),
        "forward_days": forward_days,
        "long_signal": _stats(long_matches),
        "short_signal": _stats(short_matches),
        "thresholds": {
            "adx": adx_thresh,
            "rsi_long": rsi_long_thresh,
            "rsi_short": rsi_short_thresh,
            "trend_5d_long_min": 0.10,
            "trend_5d_short_max": -0.10,
        },
    }


def find_best_thresholds(
    nifty_data: list[dict],
    *,
    forward_days: int = 1,
    min_n: int = 20,
) -> dict:
    """Sweep ADX × RSI thresholds to find the combination with the best Sharpe.

    Returns the top-N (default 5) threshold combos ranked by Sharpe ratio.
    The brain daemon can use this to ADAPT its hardcoded thresholds based
    on what actually worked historically.
    """
    enriched = _nifty_daily_features(nifty_data)
    if not enriched:
        return {"error": "no data"}

    results = []
    # Parameter sweep
    for adx_t in [0.15, 0.20, 0.25, 0.30, 0.35]:
        for rsi_long in [55, 58, 60, 62, 65]:
            for rsi_short in [35, 38, 40, 42, 45]:
                long_matches = []
                short_matches = []
                for i in range(len(enriched) - forward_days):
                    rec = enriched[i]
                    if rec["adx_proxy"] > adx_t and rec["rsi_14d"] > rsi_long and rec["trend_5d"] > 0.10:
                        forward = enriched[i + forward_days]["close"]
                        ret = (forward - rec["close"]) / rec["close"] * 100
                        long_matches.append(ret)
                    elif rec["adx_proxy"] > adx_t and rec["rsi_14d"] < rsi_short and rec["trend_5d"] < -0.10:
                        forward = enriched[i + forward_days]["close"]
                        ret = (rec["close"] - forward) / rec["close"] * 100
                        short_matches.append(ret)
                for side, matches in [("long", long_matches), ("short", short_matches)]:
                    if len(matches) < min_n:
                        continue
                    avg = statistics.mean(matches)
                    std = statistics.stdev(matches) if len(matches) > 1 else 0
                    if std == 0:
                        continue
                    sharpe = avg / std * math.sqrt(252 / forward_days)
                    results.append({
                        "side": side,
                        "adx": adx_t, "rsi": rsi_long if side == "long" else rsi_short,
                        "n": len(matches),
                        "win_rate": round(len([m for m in matches if m > 0]) / len(matches) * 100, 1),
                        "avg_return": round(avg, 3),
                        "sharpe": round(sharpe, 2),
                    })
    # Rank by Sharpe
    results.sort(key=lambda r: r["sharpe"], reverse=True)
    return {"top": results[:10], "total_combos_tested": len(results)}


def realized_volatility(nifty_data: list[dict], window: int = 20) -> float:
    """Annualized realized volatility from daily returns.

    Returns a percentage (e.g., 12.5 = 12.5% annualized vol).
    """
    enriched = _nifty_daily_features(nifty_data)
    if len(enriched) < window:
        return 15.0  # fallback: assume 15% vol
    recent = enriched[-window:]
    returns = [r["daily_return"] for r in recent]
    if not returns:
        return 15.0
    std = statistics.stdev(returns)
    return std * math.sqrt(252)  # annualize


def vol_scaling_factor(nifty_data: list[dict], target_vol_pct: float = 12.0) -> float:
    """PHASE 7 FIX: position size scaler based on realized vol.

    Higher realized vol → smaller size. Lower vol → larger size.
    Returns a multiplier in [0.25, 2.0] applied to base qty.

    target_vol_pct: desired annualized vol (default 12%). If realized vol is
    24%, position is halved (0.5x). If realized vol is 6%, position is doubled (2x).
    """
    rv = realized_volatility(nifty_data)
    if rv <= 0:
        return 1.0
    factor = target_vol_pct / rv
    # Clamp to [0.25, 2.0] for sanity
    return max(0.25, min(2.0, factor))


def get_signal_context_for_prompt() -> str:
    """Build a context block for the brain's LLM prompt with empirical stats.

    Returns a string like:
      "Historical signal context (yfinance 1y daily NIFTY):
       - Long signal (ADX>0.25, RSI>60, trend_5d>0.10): n=42, win=64%, avg=+0.42%, Sharpe=0.85
       - Short signal (ADX>0.25, RSI<40, trend_5d<-0.10): n=38, win=58%, avg=+0.31%, Sharpe=0.62
       - Realized vol (20d): 14.2% (target 12%, scale 0.85x)"
    """
    nifty_data = fetch_nifty_daily()
    if not nifty_data:
        return ""

    # Use current brain thresholds
    stats = empirical_signal_stats(nifty_data)
    if "error" in stats:
        return ""

    lines = ["\n[EMPIRICAL SIGNAL CONTEXT — yfinance NIFTY 1y daily data]"]

    if stats["long_signal"]["n"] > 0:
        ls = stats["long_signal"]
        lines.append(
            f"  LONG signal (ADX>{stats['thresholds']['adx']}, RSI>{stats['thresholds']['rsi_long']}, "
            f"trend>0.10%): n={ls['n']}, win={ls['win_rate']}%, avg={ls['avg_return']:+.2f}%, "
            f"Sharpe={ls['sharpe']}, max+={ls['max_gain']}%, max-={ls['max_loss']}%"
        )
    if stats["short_signal"]["n"] > 0:
        ss = stats["short_signal"]
        lines.append(
            f"  SHORT signal (ADX>{stats['thresholds']['adx']}, RSI<{stats['thresholds']['rsi_short']}, "
            f"trend<-0.10%): n={ss['n']}, win={ss['win_rate']}%, avg={ss['avg_return']:+.2f}%, "
            f"Sharpe={ss['sharpe']}, max+={ss['max_gain']}%, max-={ss['max_loss']}%"
        )

    rv = realized_volatility(nifty_data)
    factor = vol_scaling_factor(nifty_data)
    lines.append(f"  Realized vol (20d): {rv:.2f}% (target 12%, size scale {factor:.2f}x)")

    return "\n".join(lines)


def adapt_thresholds_from_history(
    nifty_data: list[dict],
    *,
    forward_days: int = 1,
    min_n: int = 20,
) -> dict:
    """Find the BEST threshold combination from history.

    Returns the top combo with metrics. The brain can OPTIONALLY use this
    to set its thresholds dynamically based on what historically worked.

    Format:
        {
          "best_long": {"adx": 0.25, "rsi": 60, "n": 42, "sharpe": 0.85, "win_rate": 64, "avg_return": 0.42},
          "best_short": {...},
          "recommendation": "long_adx=0.25 long_rsi=60 short_adx=0.30 short_rsi=38"
        }
    """
    sweep = find_best_thresholds(nifty_data, forward_days=forward_days, min_n=min_n)
    if "error" in sweep or not sweep.get("top"):
        return {"error": "insufficient history"}

    longs = [r for r in sweep["top"] if r["side"] == "long"]
    shorts = [r for r in sweep["top"] if r["side"] == "short"]
    best_long = longs[0] if longs else None
    best_short = shorts[0] if shorts else None

    return {
        "best_long": best_long,
        "best_short": best_short,
        "recommendation": (
            f"long_adx={best_long['adx']} long_rsi={best_long['rsi']} "
            f"short_adx={best_short['adx'] if best_short else 'n/a'} "
            f"short_rsi={best_short['rsi'] if best_short else 'n/a'}"
            if best_long else "no clear best"
        ),
        "total_combos_tested": sweep.get("total_combos_tested", 0),
    }


if __name__ == "__main__":
    print("[signal_history] fetching NIFTY daily data...")
    data = fetch_nifty_daily(lookback_days=365)
    print(f"  Got {len(data)} days")

    if not data:
        print("  No data — cannot compute stats")
        sys.exit(1)

    print("\n[empirical stats with current brain thresholds]")
    stats = empirical_signal_stats(data)
    print(json.dumps(stats, indent=2))

    print("\n[realized volatility]")
    rv = realized_volatility(data)
    print(f"  20d annualized vol: {rv:.2f}%")
    print(f"  Position size scale: {vol_scaling_factor(data):.2f}x")

    print("\n[adaptive thresholds — best historical combos]")
    adapt = adapt_thresholds_from_history(data)
    if "error" not in adapt:
        print(f"  Recommendation: {adapt['recommendation']}")
        if adapt.get("best_long"):
            bl = adapt["best_long"]
            print(f"  Best LONG: ADX={bl['adx']} RSI={bl['rsi']} Sharpe={bl['sharpe']} "
                  f"win={bl['win_rate']}% avg={bl['avg_return']:+.2f}% (n={bl['n']})")
        if adapt.get("best_short"):
            bs = adapt["best_short"]
            print(f"  Best SHORT: ADX={bs['adx']} RSI={bs['rsi']} Sharpe={bs['sharpe']} "
                  f"win={bs['win_rate']}% avg={bs['avg_return']:+.2f}% (n={bs['n']})")
    else:
        print(f"  Error: {adapt['error']}")