"""Thesis Engine — daily bias generator that fuses OI, macro, research, cross-market, news.

NOT a template. Each run builds a fresh structured thesis by pulling live
data from existing kotak_bot modules:

  1. OI analytics (max_pain, walls, PCR, GEX)        from kotak_bot.intel.oi_analytics
  2. Cross-market (GIFT Nifty, Dow fut, crude, USD/INR, VIX)  via yfinance
  3. News/sentiment                                  from kotak_bot.intel (LLM news judge)
  4. Macro calendar (RBI, US Fed, OPEC, GDP)        from kotak_bot.data.macro_calendar
  5. Kotak research PDF (daily PDF parsed)            from kotak_bot.data.kotak_research
  6. LLM synthesis                                   from kotak_brain._build_prompt (rewired)

Output: data_cache/thesis_<YYYYMMDD>_<HHMM>.json  (latest is thesis_latest.json)

Wired to cron (see scripts/install_thesis_cron.py):
  - 08:25 IST  premarket  -> drives brain_state + monday_brief
  - 10:00, 12:00, 14:00 IST  intraday refresh
  - 15:35 IST  eod_review -> feeds weekly summary
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# ---- repo paths ----
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(str(ROOT))

# ---- credentials (for any LLM calls) ----
try:
    from dotenv import load_dotenv

    _env = ROOT / "config" / "credentials.env"
    if _env.exists():
        load_dotenv(str(_env))
except Exception:
    pass

from loguru import logger

# ---- shared paths ----
from kotak_bot.utils.clock import now_ist
from kotak_bot.intel.oi_analytics import (
    oi_walls,
    max_pain,
    pcr,
    oi_aware_strike_selection,
)

DATA_CACHE = ROOT / "data_cache"
DATA_CACHE.mkdir(exist_ok=True)
THESIS_DIR = DATA_CACHE / "thesis"
THESIS_DIR.mkdir(exist_ok=True)
THESIS_LATEST = THESIS_DIR / "latest.json"
THESIS_HISTORY = DATA_CACHE / "thesis_history.jsonl"  # append-only audit log

PAPER_STATE_PATH = DATA_CACHE / "paper_state.json"
LIVE_KOTAK_QUOTES = DATA_CACHE / "live_kotak_quotes.json"  # written by feed


# ============================================================
# DATA COLLECTORS — each returns a dict, never raises
# ============================================================

def _safe(fn, *a, default=None, **kw):
    try:
        return fn(*a, **kw)
    except Exception as e:
        logger.warning(f"thesis: {fn.__name__} failed: {type(e).__name__}: {e}")
        return default


def collect_oi_snapshot() -> dict:
    """OI walls / max pain / PCR / GEX from the live Kotak tick map.

    The feed (kotak_prod_feed) writes symbol_tick_map into
    data_cache/live_kotak_quotes.json or in-memory via a singleton.
    """
    out = {
        "ts": now_ist().isoformat(),
        "available": False,
        "resistance": None,
        "support": None,
        "max_pain": None,
        "pcr": None,
        "gex_total": None,
        "strike_selection": None,
    }
    tick_map = _load_tick_map()
    if not tick_map:
        return out

    spot = _safe(_spot_from_ticks, tick_map, default=None)
    if not spot:
        return out

    out["available"] = True
    out["spot"] = spot

    walls = _safe(oi_walls, tick_map, default={}) or {}
    out["resistance"] = walls.get("resistance")
    out["support"] = walls.get("support")

    out["max_pain"] = _safe(max_pain, tick_map, default=None)
    out["pcr"] = _safe(pcr, tick_map, default=None)

    gex = _safe(_gex_total, spot, tick_map, default=None)
    out["gex_total"] = gex

    # OI-aware strike selection — uses walls + max_pain to pick condor strikes
    sel = _safe(oi_aware_strike_selection, spot, tick_map, "range", default=None)
    out["strike_selection"] = sel
    return out


def collect_cross_market() -> dict:
    """GIFT Nifty, Dow fut, crude, USD/INR, India VIX via yfinance (best-effort)."""
    out = {
        "ts": now_ist().isoformat(),
        "gift_nifty": None,
        "dow_fut": None,
        "dow_spot": None,
        "crude_oil": None,
        "usdinr": None,
        "india_vix": None,
        "dxy": None,
        "global_cues": "unknown",
    }
    try:
        import yfinance as yf
    except Exception:
        return out

    tickers = {
        "nifty_spot": "^NSEI",        # NIFTY 50 spot (proxy for GIFT Nifty until we wire a real feed)
        "banknifty_spot": "^NSEBANK",  # BANKNIFTY spot
        "dow_fut": "YM=F",           # Dow futures
        "dow_spot": "^DJI",
        "crude_oil": "CL=F",
        "usdinr": "INR=X",           # USD/INR
        "india_vix": "^INDIAVIX",
        "dxy": "DX-Y.NYB",
    }
    for key, sym in tickers.items():
        try:
            t = yf.Ticker(sym)
            hist = t.history(period="1d")
            if hist is not None and not hist.empty and "Close" in hist.columns:
                out[key] = float(hist["Close"].iloc[-1])
        except Exception:
            pass
        time.sleep(0.05)  # be polite to Yahoo

    # derive a global-cue label
    cues = []
    if out["gift_nifty"] and out["dow_fut"]:
        diff = out["gift_nifty"] - out.get("spot", out["gift_nifty"])  # no spot here, leave neutral
        cues.append("GIFT flat")
    if out["crude_oil"] and out["crude_oil"] > 80:
        cues.append("crude hot (inflation pressure)")
    if out["india_vix"] and out["india_vix"] > 16:
        cues.append("VIX elevated")
    if out["india_vix"] and out["india_vix"] < 12:
        cues.append("VIX compressed")
    out["global_cues"] = " | ".join(cues) if cues else "no strong cue"
    return out


def collect_macro() -> dict:
    """Upcoming macro events (RBI, US Fed, OPEC, GDP) in next 48h."""
    out = {"ts": now_ist().isoformat(), "next_event": None, "window_min": None}
    try:
        from kotak_bot.data.macro_calendar import MacroCalendar

        cal = MacroCalendar()
        # Strip tz info — MacroCalendar uses naive datetimes internally
        from datetime import datetime as _dt

        now_naive = _dt.now()
        evt = _safe(cal.next_event, now_naive, default=None)
        if evt:
            out["next_event"] = evt
            win = _safe(cal.get_event_window, now_naive, 60, default=None)
            if isinstance(win, dict):
                out["window_min"] = win.get("minutes_until", win.get("minutes_to"))
            elif isinstance(win, (int, float)):
                out["window_min"] = win
    except Exception as e:
        logger.debug(f"thesis: macro_calendar unavailable: {e}")
    return out


def collect_research() -> dict:
    """Parse today's Kotak research PDF (if downloaded) for the house view."""
    out = {"ts": now_ist().isoformat(), "available": False, "summary": None, "bias": None, "key_levels": {}}
    try:
        from kotak_bot.data.kotak_research import daily_research_summary

        summary = _safe(daily_research_summary, default=None)
        if not summary:
            return out
        out["available"] = True
        out["summary"] = summary.get("summary") or summary.get("view")
        out["bias"] = summary.get("bias") or summary.get("direction")
        kl = summary.get("key_levels") or {}
        out["key_levels"] = kl
    except Exception as e:
        logger.debug(f"thesis: kotak_research unavailable: {e}")
    return out


def collect_news() -> dict:
    """News sentiment — try cached LLM news judge result, else simple keyword count.

    Live LLM call per-thesis-run is too slow (5-15s) and burns budget.
    Use a cached file written by the news cron. Fall back to keyword scan
    if nothing is cached yet (typical at 08:30 premarket).
    """
    out = {"ts": now_ist().isoformat(), "score": 0.0, "n_items": 0, "headlines": []}

    # 1. Try cached aggregate file
    cache = DATA_CACHE / "news_aggregate.json"
    if cache.exists():
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            age_min = (now_ist() - _parse_dt(data.get("ts"))).total_seconds() / 60 if data.get("ts") else 999
            if age_min < 120:  # 2h freshness window
                out["score"] = float(data.get("score", 0.0))
                out["n_items"] = int(data.get("n", 0))
                out["headlines"] = list(data.get("headlines", []))[:5]
                out["source"] = "cache"
                return out
        except Exception:
            pass

    # 2. Cheap keyword scan on log tail — always works
    out.update(_keyword_news_scan())
    out["source"] = "keyword"
    return out


def _parse_dt(s):
    """Parse ISO datetime, strip tz."""
    from datetime import datetime

    if not s:
        return now_ist()
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return dt
    except Exception:
        return now_ist().replace(tzinfo=None)


def _gather_recent_headlines() -> list[str]:
    """Best-effort headline source. Reads tail of bot.log + any cached news file.

    Cheap; if a real news API is wired later, plug it in here.
    """
    heads: list[str] = []
    for path in (ROOT / "logs" / "bot.log", ROOT / "data_cache" / "news_cache.txt"):
        if not path.exists():
            continue
        try:
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()[-300:]:
                low = line.lower()
                if any(w in low for w in (
                    "fii", "dii", "rbi", "fed", "cpi", "inflation", "gdp",
                    "opec", "crude", "crude oil", "nifty", "sensex",
                    "russia", "ukraine", "israel", "iran", "tariff",
                    "earnings", "rbi policy", "monetary",
                )):
                    heads.append(line.strip()[:200])
                if len(heads) >= 20:
                    break
        except Exception:
            pass
    return heads


def collect_paper_state() -> dict:
    """Quick read of current paper positions, PnL, capital."""
    out = {"ts": now_ist().isoformat(), "cash": None, "realized": None, "open_count": 0, "open": []}
    if not PAPER_STATE_PATH.exists():
        return out
    try:
        with open(PAPER_STATE_PATH, "r", encoding="utf-8") as f:
            st = json.load(f)
        out["cash"] = st.get("cash")
        out["realized"] = st.get("realized_pnl")
        pos = st.get("positions") or {}
        out["open_count"] = len(pos)
        for tid, p in list(pos.items())[:6]:
            out["open"].append(
                {
                    "id": tid,
                    "symbol": p.get("symbol") or p.get("tradingsymbol"),
                    "qty": p.get("qty") or p.get("quantity"),
                    "pnl": p.get("pnl") or p.get("unrealized"),
                }
            )
    except Exception as e:
        logger.debug(f"thesis: paper_state read failed: {e}")
    return out


# ============================================================
# HELPERS
# ============================================================

def _load_tick_map() -> dict:
    """Read the in-process tick map snapshot. Best-effort.

    Tries (in order):
      1. live_kotak_quotes.json (the feed writes one periodically)
      2. read it via the live_feed singleton if importable
    """
    if LIVE_KOTAK_QUOTES.exists():
        try:
            data = json.loads(LIVE_KOTAK_QUOTES.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data:
                return data
        except Exception:
            pass
    # Fallback: try the in-process feed via the public helper
    try:
        from kotak_bot.data.live_feed import get_snapshot  # type: ignore

        snap = _safe(get_snapshot, default=None)
        if isinstance(snap, dict) and snap:
            return snap
    except Exception:
        pass
    return {}


def _spot_from_ticks(tick_map: dict) -> float | None:
    """Find the underlying spot LTP from the tick map. NIFTY/BANKNIFTY both work."""
    # Try common keys
    for k in ("NIFTY", "NIFTY 50", "BANKNIFTY", "NIFTY50"):
        if k in tick_map and isinstance(tick_map[k], dict):
            ltp = tick_map[k].get("ltp") or tick_map[k].get("last_price")
            if ltp:
                return float(ltp)
    # Fallback: any key with ltp
    for v in tick_map.values():
        if isinstance(v, dict) and v.get("ltp"):
            return float(v["ltp"])
    return None


def _gex_total(spot: float, tick_map: dict) -> float | None:
    try:
        from kotak_bot.intel.oi_analytics import gex

        res = gex(spot, tick_map, contract_multiplier=1)
        if isinstance(res, dict):
            return float(res.get("total_gex", res.get("gex", 0.0)) or 0.0)
    except Exception:
        pass
    return None


def _keyword_news_scan() -> dict:
    """Very rough news sentiment from log tail — used when LLM judge unavailable."""
    out = {"score": 0.0, "n_items": 0, "headlines": []}
    log = ROOT / "logs" / "bot.log"
    if not log.exists():
        return out
    try:
        text = "\n".join(log.read_text(encoding="utf-8", errors="ignore").splitlines()[-200:])
    except Exception:
        return out

    pos_words = ("bullish", "surge", "rally", "gains", "record high", "fii buying", "upgrade", "positive")
    neg_words = ("bearish", "falls", "drop", "slump", "fii selling", "downgrade", "tension", "war", "miss")
    score = 0.0
    n = 0
    for line in text.splitlines():
        low = line.lower()
        for w in pos_words:
            if w in low:
                score += 0.1
                n += 1
                break
        for w in neg_words:
            if w in low:
                score -= 0.1
                n += 1
                break
    out["score"] = max(-1.0, min(1.0, score))
    out["n_items"] = n
    return out


# ============================================================
# THESIS SYNTHESIS
# ============================================================

def synthesize_thesis(parts: dict) -> dict:
    """Combine the parts into a single, structured, decision-ready thesis.

    Output schema (json-serializable, no LLM dependency for the structure —
    an LLM can later be wired in to enrich `narrative`):
      {
        ts, ist_time, run_kind (premarket|intraday|eod),
        regime: pin | range | breakout_up | breakout_down | volatile | quiet,
        bias: bullish | bearish | neutral | cautious,
        confidence: 0..1,
        risk_budget_pct: 0..100,
        max_positions: int,
        expected_move_pts: float,
        expected_range: [low, high],
        preferred_strategies: [..],
        avoid_strategies: [..],
        specific_strikes: {trade, ce_short, pe_short, wings, ...} | None,
        triggers: {force_square: bool, no_new_trades: bool, notes: str},
        data: {oi, xmkt, macro, research, news, paper}
        narrative: str  (1-paragraph human-readable)
      }
    """
    oi = parts.get("oi", {})
    xmkt = parts.get("xmkt", {})
    macro = parts.get("macro", {})
    research = parts.get("research", {})
    news = parts.get("news", {})
    paper = parts.get("paper", {})

    spot = oi.get("spot") or xmkt.get("nifty_spot") or xmkt.get("banknifty_spot")
    max_p = oi.get("max_pain")
    res = oi.get("resistance")
    sup = oi.get("support")
    pcr_v = oi.get("pcr")
    gex = oi.get("gex_total")
    vix = xmkt.get("india_vix") or 14.0
    n_score = news.get("score", 0.0)
    r_bias = (research.get("bias") or "").lower() if research.get("bias") else ""

    # ---------- regime ----------
    if gex is not None and abs(gex) > 0:
        # Positive GEX = long vol dampening (pin), negative = long vol expansion (breakout prone)
        if gex > 0 and (res and sup) and abs((res or 0) - (sup or 0)) < 600:
            regime = "pin"
        elif gex < -50_000_000:
            regime = "breakout_prone"
        else:
            regime = "range"
    elif max_p and spot and abs(spot - max_p) < 30:
        regime = "pin"
    elif vix and vix > 18:
        regime = "volatile"
    else:
        regime = "range"

    # ---------- bias (consensus) ----------
    votes = []
    if oi.get("resistance") and spot:
        if spot < (oi["resistance"] - 50):
            votes.append("bullish")  # room to upside
        elif spot > (oi["resistance"] - 20):
            votes.append("cautious")  # at wall
    if oi.get("support") and spot:
        if spot < (oi["support"] + 20):
            votes.append("cautious")
    if pcr_v is not None:
        if pcr_v > 1.2:
            votes.append("bullish")
        elif pcr_v < 0.8:
            votes.append("bearish")
    if n_score > 0.2:
        votes.append("bullish")
    elif n_score < -0.2:
        votes.append("bearish")
    if r_bias in ("bullish", "bearish", "neutral", "cautious"):
        votes.append(r_bias)

    if not votes:
        bias = "neutral"
        confidence = 0.3
    else:
        tally = {b: votes.count(b) for b in ("bullish", "bearish", "neutral", "cautious")}
        bias = max(tally, key=tally.get)
        total = sum(tally.values())
        confidence = round(0.4 + 0.6 * (tally[bias] / total), 2)
    # downgrade confidence if events are imminent
    if macro.get("window_min") is not None and 0 <= macro["window_min"] <= 120:
        confidence = min(confidence, 0.55)

    # ---------- risk_budget ----------
    if bias == "cautious" or regime == "volatile":
        risk_budget = 25
        max_pos = 1
    elif regime == "pin" and confidence < 0.55:
        risk_budget = 30
        max_pos = 1
    elif confidence >= 0.7 and bias in ("bullish", "bearish"):
        risk_budget = 70
        max_pos = 2
    else:
        risk_budget = 45
        max_pos = 2

    # ---------- expected range ----------
    if spot and vix:
        # rough daily 1-sigma move: spot * vix/100 * 1/sqrt(252)
        sigma = spot * (vix / 100.0) * 0.063
        expected_low = max(0.0, spot - sigma)
        expected_high = spot + sigma
    else:
        expected_low, expected_high = None, None

    # ---------- strategy picks ----------
    preferred = []
    avoid = []
    if regime == "pin" or (max_p and spot and abs(spot - max_p) < 50):
        preferred += ["iron_butterfly", "iron_condor"]
    elif regime == "range":
        preferred += ["iron_condor", "short_strangle"]
    elif regime == "breakout_prone":
        preferred += ["long_straddle", "event_straddle"]
        avoid += ["short_strangle", "iron_condor"]
    elif regime == "volatile":
        preferred += ["calendar", "long_straddle"]
        avoid += ["naked_short"]
    # macro event filter
    if macro.get("window_min") is not None and 0 <= macro["window_min"] <= 60:
        avoid += ["short_strangle", "iron_condor"]  # gamma spike danger
    # bias-driven overrides
    if bias == "bullish" and confidence > 0.6:
        preferred += ["bull_call_vertical"]
    if bias == "bearish" and confidence > 0.6:
        preferred += ["bear_put_vertical"]
    # de-dupe, keep order
    seen = set()
    preferred = [s for s in preferred if not (s in seen or seen.add(s))]

    # ---------- triggers ----------
    triggers = {
        "force_square": bool(macro.get("window_min") is not None and 0 <= macro["window_min"] <= 30),
        "no_new_trades": bool(
            (macro.get("window_min") is not None and 0 <= macro["window_min"] <= 90)
            or regime == "volatile"
        ),
        "notes": _trigger_notes(regime, macro, oi),
    }

    # ---------- specific strikes ----------
    strikes = oi.get("strike_selection")

    # ---------- narrative ----------
    narrative = _build_narrative(
        regime=regime, bias=bias, confidence=confidence, spot=spot, max_p=max_p,
        res=res, sup=sup, pcr=pcr_v, gex=gex, vix=vix, news=n_score, research=r_bias,
        macro=macro,
    )

    return {
        "ts": now_ist().isoformat(timespec="seconds"),
        "ist_time": now_ist().strftime("%Y-%m-%d %H:%M:%S"),
        "regime": regime,
        "bias": bias,
        "confidence": confidence,
        "risk_budget_pct": risk_budget,
        "max_positions": max_pos,
        "expected_move_pts": round(sigma, 2) if (spot and vix) else None,
        "expected_range": [expected_low, expected_high] if (spot and vix) else None,
        "preferred_strategies": preferred[:4],
        "avoid_strategies": avoid[:4],
        "specific_strikes": strikes,
        "triggers": triggers,
        "narrative": narrative,
        "data": {
            "oi": oi,
            "xmkt": xmkt,
            "macro": macro,
            "research": research,
            "news": news,
            "paper": paper,
        },
    }


def _trigger_notes(regime: str, macro: dict, oi: dict) -> str:
    bits = []
    if macro.get("window_min") is not None:
        bits.append(f"event in {int(macro['window_min'])}m")
    if regime == "breakout_prone":
        bits.append("negative GEX — expect expansion")
    if regime == "pin":
        bits.append("positive GEX + tight range — mean reversion favored")
    if oi.get("pcr") is not None and oi["pcr"] < 0.8:
        bits.append(f"PCR {oi['pcr']:.2f} — call dominated, put writers relaxed")
    return " | ".join(bits) or "no special triggers"


def _build_narrative(**kw) -> str:
    parts = []
    s = kw.get("spot")
    if s:
        parts.append(f"Spot ~{int(s)}")
    if kw.get("max_p"):
        parts.append(f"max pain {int(kw['max_p'])}")
    if kw.get("res") and kw.get("sup"):
        parts.append(f"walls {int(kw['sup'])}/{int(kw['res'])}")
    if kw.get("pcr") is not None:
        parts.append(f"PCR {kw['pcr']:.2f}")
    if kw.get("gex") is not None:
        sign = "+" if kw["gex"] >= 0 else "-"
        parts.append(f"GEX {sign}{abs(int(kw['gex']))/1e7:.1f}cr")
    if kw.get("vix"):
        parts.append(f"VIX {kw['vix']:.1f}")
    if kw.get("news") is not None and kw["news"] != 0:
        sign = "+" if kw["news"] > 0 else ""
        parts.append(f"news {sign}{kw['news']:.2f}")
    if kw.get("research"):
        parts.append(f"Kotak {kw['research']}")
    if kw.get("macro", {}).get("next_event"):
        evt = kw["macro"]["next_event"]
        name = evt.get("name") if isinstance(evt, dict) else str(evt)
        if kw["macro"].get("window_min") is not None:
            parts.append(f"event {name} in {int(kw['macro']['window_min'])}m")
    thesis_bits = " | ".join(parts)
    return (
        f"**{kw['regime'].upper()}** regime, {kw['bias']} (conf {kw['confidence']:.0%}). "
        f"{thesis_bits}. "
        f"Playbook: {kw.get('risk_budget', 45):.0f}% capital, {kw.get('max_pos', 2)} max positions."
    )


# ============================================================
# ENTRYPOINT
# ============================================================

def run(run_kind: str = "intraday", deliver: bool = False) -> dict:
    t0 = time.time()
    parts = {
        "oi": collect_oi_snapshot(),
        "xmkt": collect_cross_market(),
        "macro": collect_macro(),
        "research": collect_research(),
        "news": collect_news(),
        "paper": collect_paper_state(),
    }
    thesis = synthesize_thesis(parts)
    thesis["run_kind"] = run_kind
    thesis["build_ms"] = int((time.time() - t0) * 1000)

    # persist
    stamp = now_ist().strftime("%Y%m%d_%H%M%S")
    out = THESIS_DIR / f"thesis_{stamp}.json"
    out.write_text(json.dumps(thesis, indent=2, default=str), encoding="utf-8")
    THESIS_LATEST.write_text(json.dumps(thesis, indent=2, default=str), encoding="utf-8")
    with open(THESIS_HISTORY, "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": thesis["ts"], "regime": thesis["regime"], "bias": thesis["bias"], "conf": thesis["confidence"]}) + "\n")

    if deliver:
        _deliver(thesis)

    logger.info(
        f"thesis: regime={thesis['regime']} bias={thesis['bias']} "
        f"conf={thesis['confidence']:.0%} risk={thesis['risk_budget_pct']}% "
        f"build_ms={thesis['build_ms']}"
    )
    return thesis


def _deliver(thesis: dict) -> None:
    """Send to Telegram if creds are set; else just print to stdout."""
    msg = (
        f"📊 *THESIS* {thesis['ist_time']}\n"
        f"Regime: *{thesis['regime'].upper()}* | Bias: *{thesis['bias']}* "
        f"(conf {thesis['confidence']:.0%})\n"
        f"Risk: {thesis['risk_budget_pct']}% | Max pos: {thesis['max_positions']}\n"
        f"\n{thesis['narrative']}\n"
    )
    if thesis.get("specific_strikes"):
        ss = thesis["specific_strikes"]
        if isinstance(ss, dict):
            ce = ss.get("ce_short")
            pe = ss.get("pe_short")
            if ce and pe:
                msg += f"\n🎯 Strikes (OI-aware): CE short {ce} | PE short {pe}\n"
    try:
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        chat = os.environ.get("TELEGRAM_CHAT_ID")
        if token and chat:
            import httpx
            httpx.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat, "text": msg, "parse_mode": "Markdown"},
                timeout=10,
            )
    except Exception as e:
        logger.debug(f"thesis: telegram send failed: {e}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("kind", nargs="?", default="intraday", choices=["premarket", "intraday", "eod"])
    p.add_argument("--deliver", action="store_true")
    args = p.parse_args()
    thesis = run(args.kind, deliver=args.deliver)
    print(json.dumps(thesis, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
