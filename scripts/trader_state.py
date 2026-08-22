"""trader_state.py — thin data fetcher for the trader (Mavis) to consume.

Does NOT make decisions. Does NOT call any LLM. Just collects market + paper state
+ candle context + research + macro events into one JSON blob so Mavis (in a
fresh cron session) can read it and think.

Usage: python scripts/trader_state.py
Prints a single JSON object to stdout. No side effects beyond reading files.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    _env = ROOT / "config" / "credentials.env"
    if _env.exists():
        load_dotenv(str(_env))
except Exception:
    pass


def now_ist_str() -> str:
    from kotak_bot.utils.clock import now_ist
    return now_ist().strftime("%Y-%m-%d %H:%M:%S")


def market_session() -> str:
    try:
        from kotak_bot.utils.clock import market_session as _ms
        return _ms()
    except Exception:
        return "unknown"


def load_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default if default is not None else {}


def tail_log(path: Path, n: int = 20) -> list[str]:
    try:
        if not path.exists():
            return []
        return path.read_text(encoding="utf-8", errors="ignore").splitlines()[-n:]
    except Exception:
        return []


def get_vix() -> float:
    try:
        from kotak_bot.utils.clock import get_india_vix, fetch_india_vix
        # refresh from yfinance if cache is stale
        try:
            fetch_india_vix(force=False)
        except Exception:
            pass
        return float(get_india_vix())
    except Exception:
        return 14.0


def compact_positions(paper: dict) -> list[dict]:
    pos = paper.get("positions", {}) or {}
    out = []
    for sym, p in pos.items():
        if p.get("qty", 0) == 0:
            continue
        out.append({
            "sym": sym,
            "qty": p.get("qty", 0),
            "expiry": p.get("expiry"),
            "avg_price": p.get("avg_price"),
            "strategy": p.get("tag", "").split("_")[0] if p.get("tag") else None,
        })
    return out


def get_recent_candles(symbol: str = "NIFTY", days: int = 5) -> dict:
    """Fetch last N days of NIFTY/BANKNIFTY daily candles. Returns dict with
    recent OHLC + a 5-day momentum % + trend direction. Fails silently."""
    out = {
        "symbol": symbol,
        "available": False,
        "last_close": None,
        "last_5d_change_pct": None,
        "trend": "unknown",  # up | down | flat
        "range_pct": None,   # (high-low)/close of last day
        "candles": [],       # list of {date, open, high, low, close, volume}
        "source": None,
    }
    try:
        from kotak_bot.data.historical import HistoricalData
        hd = HistoricalData()
        df = hd.get_equity_ohlc(symbol, days=days + 5, interval="1d")
        if df is None or df.empty:
            return out
        # Take last `days` rows
        df = df.tail(days).reset_index(drop=True)
        candles = []
        for _, row in df.iterrows():
            candles.append({
                "date": str(row.get("date", ""))[:10],
                "open": float(row.get("open", 0)) if row.get("open") is not None else None,
                "high": float(row.get("high", 0)) if row.get("high") is not None else None,
                "low": float(row.get("low", 0)) if row.get("low") is not None else None,
                "close": float(row.get("close", 0)) if row.get("close") is not None else None,
                "volume": float(row.get("volume", 0)) if row.get("volume") is not None else None,
            })
        out["candles"] = candles
        out["available"] = True
        if len(candles) >= 1:
            out["last_close"] = candles[-1]["close"]
            if candles[-1]["close"] and candles[-1]["high"] and candles[-1]["low"]:
                rng = candles[-1]["high"] - candles[-1]["low"]
                out["range_pct"] = round((rng / candles[-1]["close"]) * 100, 2)
        if len(candles) >= 2 and candles[-1]["close"] and candles[0]["close"]:
            change = (candles[-1]["close"] - candles[0]["close"]) / candles[0]["close"]
            out["last_5d_change_pct"] = round(change * 100, 2)
            if change > 0.005:
                out["trend"] = "up"
            elif change < -0.005:
                out["trend"] = "down"
            else:
                out["trend"] = "flat"
        out["source"] = "yfinance"  # HistoricalData prefers yfinance
    except Exception as e:
        out["error"] = str(e)[:200]
    return out


def candle_regime(candles: dict, vix: float) -> dict:
    """Lightweight candle-aware regime using price action + VIX.
    Returns {regime, confidence, reason} — separate from the heavier RegimeDetector
    in kotak_brain.py (which needs OHLC+ADX). This is the cron-friendlier version
    that runs in <1s.
    """
    trend = candles.get("trend", "unknown")
    rng = candles.get("range_pct")
    change = candles.get("last_5d_change_pct")
    out = {"regime": "unknown", "confidence": 0.4, "reason": ""}
    if candles.get("available") is False:
        out["reason"] = "candles_unavailable"
        return out
    # Decide
    if vix >= 18.0:
        out["regime"] = "volatile"
        out["confidence"] = 0.75
        out["reason"] = f"vix={vix:.1f} elevated"
    elif change is not None and abs(change) >= 1.5:
        out["regime"] = "trending"
        direction = "up" if change > 0 else "down"
        out["confidence"] = 0.7
        out["reason"] = f"5d_change={change:+.2f}% → {direction}"
    elif rng is not None and rng < 1.0 and vix < 14:
        out["regime"] = "range"
        out["confidence"] = 0.7
        out["reason"] = f"range={rng:.2f}% tight + vix={vix:.1f} low"
    elif trend == "up" and vix < 16:
        out["regime"] = "trending"
        out["confidence"] = 0.55
        out["reason"] = f"trend=up, vix={vix:.1f}"
    elif trend == "down" and vix < 16:
        out["regime"] = "trending"
        out["confidence"] = 0.55
        out["reason"] = f"trend=down, vix={vix:.1f}"
    else:
        out["regime"] = "range"
        out["confidence"] = 0.45
        out["reason"] = f"default range (vix={vix:.1f}, change={change})"
    return out


def get_research_summary() -> dict:
    """Fetch latest Kotak Securities research summary (max_pain, PCR, FII flows, range)."""
    out = {
        "available": False,
        "summary": "",
        "metrics": {},
        "extracted_at": None,
    }
    try:
        from kotak_bot.data.kotak_research import daily_research_summary
        s = daily_research_summary()
        if isinstance(s, dict) and "error" not in s:
            out["available"] = True
            out["extracted_at"] = s.get("extracted_at")
            out["metrics"] = {
                "max_pain": s.get("max_pain"),
                "pcr": s.get("pcr"),
                "fii_net_oi": s.get("fii_net_oi"),
                "spot_expiry_range": s.get("spot_expiry_range"),
            }
            # Build a one-line human summary
            parts = []
            if s.get("max_pain") is not None:
                parts.append(f"Max Pain={s['max_pain']:.0f}")
            if s.get("pcr") is not None:
                parts.append(f"PCR={s['pcr']:.2f}")
            if s.get("fii_net_oi") is not None:
                parts.append(f"FII Net OI={s['fii_net_oi']:+.0f}")
            if s.get("spot_expiry_range"):
                parts.append(f"Expiry range: {s['spot_expiry_range']}")
            out["summary"] = " | ".join(parts) if parts else "(no metrics parsed)"
            out["source"] = s.get("source")
        else:
            out["error"] = s.get("error", "unknown") if isinstance(s, dict) else "non-dict result"
    except Exception as e:
        out["error"] = str(e)[:200]
    return out


def get_macro_events(days_ahead: int = 3) -> dict:
    """Get upcoming macro events (RBI, Fed, GDP, expiry) in next N days.
    Also flags if any event is in the intraday blackout window.
    """
    out = {
        "upcoming": [],          # list of {name, date, time_ist, importance, in_blackout}
        "in_blackout": False,
        "next_event_min": None,  # minutes to next event
    }
    try:
        from kotak_bot.data.macro_calendar import MacroCalendar
        from kotak_bot.utils.clock import now_ist
        cal = MacroCalendar()
        ist_now = now_ist().replace(tzinfo=None)  # macro events stored as naive IST
        events = []
        next_min = None
        for ev in cal.events:
            ev_dt = ev.get("datetime_ist")
            if ev_dt is None:
                continue
            mins_to = (ev_dt - ist_now).total_seconds() / 60.0
            if mins_to < -60:  # skip events more than 1h in the past
                continue
            if mins_to > days_ahead * 24 * 60:
                continue
            in_blackout = -60 <= mins_to <= 15  # matches clock.py event_blackout settings
            events.append({
                "name": ev.get("name", ""),
                "datetime_ist": ev_dt.strftime("%Y-%m-%d %H:%M"),
                "importance": ev.get("importance", 0),
                "direction_hint": ev.get("direction_hint", "neutral"),
                "minutes_away": int(mins_to),
                "in_blackout": in_blackout,
            })
            if next_min is None or (0 < mins_to < next_min):
                next_min = mins_to
        events.sort(key=lambda e: e["minutes_away"])
        out["upcoming"] = events[:5]  # cap to 5
        out["in_blackout"] = any(e["in_blackout"] for e in events)
        out["next_event_min"] = int(next_min) if next_min is not None else None
    except Exception as e:
        out["error"] = str(e)[:200]
    return out


def get_strategy_version() -> dict:
    """Read the current strategy code version from git. Best-effort, fast."""
    out: dict = {"available": False}
    try:
        import subprocess
        def _g(*args):
            r = subprocess.run(
                ["git", "-C", str(ROOT)] + list(args),
                capture_output=True, text=True, timeout=5, check=False,
            )
            return r.stdout.strip() if r.returncode == 0 else ""
        out["head_short"] = _g("rev-parse", "--short", "HEAD")
        out["branch"] = _g("rev-parse", "--abbrev-ref", "HEAD")
        out["strategy_short"] = _g("log", "-1", "--format=%h", "--", "kotak_bot/strategy/")
        out["strategy_msg"] = _g("log", "-1", "--format=%s", "--", "kotak_bot/strategy/")
        diff = _g("status", "--short", "--", "kotak_bot/strategy/")
        out["strategy_dirty"] = bool(diff)
        out["available"] = bool(out["head_short"])
    except Exception as e:
        out["error"] = str(e)[:200]
    return out


def main() -> int:
    paper = load_json(ROOT / "data_cache" / "paper_state.json")
    brain = load_json(ROOT / "data_cache" / "brain_state.json")
    vix = get_vix()

    # Candle context (fast, ~1s)
    nifty_candles = get_recent_candles("NIFTY", days=5)
    banknifty_candles = get_recent_candles("BANKNIFTY", days=5)
    candles_regime_n = candle_regime(nifty_candles, vix)
    candles_regime_bn = candle_regime(banknifty_candles, vix)

    # Macro + research (best-effort, don't fail the script)
    macro = get_macro_events(days_ahead=3)
    research = get_research_summary()

    # Strategy code version (for audit trail)
    strategy_version = get_strategy_version()

    state = {
        "ts_ist": now_ist_str(),
        "market_session": market_session(),
        "vix": vix,
        "cash": paper.get("cash", 0),
        "realized_pnl": paper.get("realized_pnl", 0),
        "open_positions": compact_positions(paper),
        "last_brain": brain.get("last_decision"),
        "last_actions": load_json(ROOT / "data_cache" / "brain_actions.json"),
        "bot_log_tail": tail_log(ROOT / "Logs" / "bot.log", n=15),

        # candle-aware context
        "candles": {
            "NIFTY": nifty_candles,
            "BANKNIFTY": banknifty_candles,
        },
        "candle_regime": {
            "NIFTY": candles_regime_n,
            "BANKNIFTY": candles_regime_bn,
        },

        # macro events
        "macro": macro,

        # research summary (Kotak Securities daily)
        "research": research,

        # NEW: strategy code version (git SHA)
        "strategy_version": strategy_version,
    }
    print(json.dumps(state, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
