"""Build the Monday pre-market brief by combining:
  - weekend_intel.json (markets + RSS news from weekend_intel.py)
  - macro_calendar events (RBI, Fed, US CPI, GDP, expiry)
  - latest backtest_sweep.json (best strategies, current regime)
  - current paper_state.json (cash, open positions, P&L)

Output: data_cache/monday_brief.json
  {
    "as_of": "...",
    "next_session_open_ist": "2026-08-25T09:15:00+05:30",
    "weekend_summary": "human-readable 1-2 line summary",
    "key_risks": [...],
    "key_catalysts": [...],
    "regime_hint": "risk_on | risk_off | neutral",
    "india_open_gap_signal": "gap_up | gap_down | flat",
    "macro_blackout_soon": bool,
    "macro_blackout_event": {...} or null,
    "recommended_posture": "conservative | normal | aggressive",
    "max_risk_per_trade_pct": float (1.0, 2.0, or 3.0),
    "skip_first_30min": bool,
    "preferred_strategies": [...],
    "rationale": "..."
  }

Decision rules (rule-based; Mavis may override with LLM later):
  - regime_hint=risk_off OR gap_down → conservative, risk 1.0%, skip_first_30min=True
  - regime_hint=risk_on AND gap_up → normal, risk 2.0%, skip_first_30min=False
  - macro blackout in next 4h → conservative, skip_first_30min=True
  - macro blackout in next 24h → normal-but-cautious, risk 1.5%
  - recent realized_pnl drawdown > 5% → conservative
  - default → normal, risk 2.0%, skip_first_30min=False
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger

# Import macro_calendar (lives in kotak_bot.data)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from kotak_bot.data.macro_calendar import MacroCalendar

CACHE_DIR = Path("data_cache")
INTEL_PATH = CACHE_DIR / "weekend_intel.json"
BACKTEST_PATH = CACHE_DIR / "backtest_sweep.json"
STATE_PATH = CACHE_DIR / "paper_state.json"
OUTPUT_PATH = CACHE_DIR / "monday_brief.json"


def _next_monday_open_ist(now: datetime) -> datetime:
    """If today is Mon-Fri before 9:15 IST, return today's 9:15. Else next Monday 9:15."""
    # 0=Mon, 6=Sun
    days_ahead = (7 - now.weekday()) % 7
    # If Monday and before open, use today
    if now.weekday() == 0:
        days_ahead = 0
    # If Saturday/Sunday, jump to Monday
    next_monday = now.date() + timedelta(days=days_ahead)
    return datetime.combine(next_monday, datetime.min.time()).replace(hour=9, minute=15)


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"could not load {path}: {e}")
        return {}


def _derive_key_risks(intel: dict, macro: list) -> list[str]:
    risks = []
    markets = intel.get("markets", {})
    # Crude spike
    wti_5d = markets.get("WTI_CRUDE", {}).get("change_5d_pct", 0)
    brent_5d = markets.get("BRENT_CRUDE", {}).get("change_5d_pct", 0)
    if wti_5d > 2 or brent_5d > 2:
        risks.append(f"Oil +{max(wti_5d, brent_5d):.1f}% this week — India import bill widens, INR pressure")
    # USDINR weak
    usdinr_5d = markets.get("USDINR", {}).get("change_5d_pct", 0)
    if usdinr_5d > 0.5:
        risks.append(f"USD/INR +{usdinr_5d:.2f}% — rupee weakening, FII outflow risk")
    # US 5d weak
    sp_5d = markets.get("SP500", {}).get("change_5d_pct", 0)
    if sp_5d < -1:
        risks.append(f"S&P 500 {sp_5d:+.2f}% over 5d — risk-off in US, EM contagion")
    # VIX elevated
    us_vix = markets.get("US_VIX", {}).get("last", 15)
    if us_vix > 18:
        risks.append(f"US VIX {us_vix:.1f} — elevated, expect gaps and whipsaws")
    # Macro events in next 4h / 24h
    ist_now = datetime.now()
    for e in macro:
        try:
            dt = e["datetime_ist"]
        except KeyError:
            continue
        if dt < ist_now:
            continue
        delta_h = (dt - ist_now).total_seconds() / 3600
        if delta_h < 4 and e.get("importance", 0) >= 3:
            risks.append(f"Major event in {delta_h:.1f}h: {e['name']} — high impact, expect volatility")
        elif delta_h < 24 and e.get("importance", 0) >= 3:
            risks.append(f"Major event in {delta_h:.0f}h: {e['name']}")
    # Bearish news from RSS
    for n in intel.get("key_news", [])[:5]:
        if n.get("sentiment") == "bearish" and n.get("score", 0) <= -2:
            risks.append(f"News: {n['title'][:90]}")
            if len(risks) >= 6:
                break
    return risks[:6]


def _derive_key_catalysts(intel: dict, macro: list) -> list[str]:
    catalysts = []
    markets = intel.get("markets", {})
    # Risk-on signals
    sp_1d = markets.get("SP500", {}).get("change_1d_pct", 0)
    if sp_1d > 0.5:
        catalysts.append(f"S&P +{sp_1d:.2f}% Friday — US tailwind for Monday Asia open")
    nq_1d = markets.get("NASDAQ", {}).get("change_1d_pct", 0)
    if nq_1d > 0.5:
        catalysts.append(f"Nasdaq +{nq_1d:.2f}% Friday — tech rally spillover")
    # Weak dollar
    dxy_5d = markets.get("DOLLAR_INDEX", {}).get("change_5d_pct", 0)
    if dxy_5d < -0.5:
        catalysts.append(f"Dollar index {dxy_5d:+.2f}% — weaker USD = EM tailwind")
    # India VIX low
    ivix = markets.get("INDIA_VIX", {}).get("last", 15)
    if ivix < 12:
        catalysts.append(f"India VIX {ivix:.1f} — calm, premium-selling favorable")
    # Bullish news
    for n in intel.get("key_news", [])[:5]:
        if n.get("sentiment") == "bullish" and n.get("score", 0) >= 2:
            catalysts.append(f"News: {n['title'][:90]}")
            if len(catalysts) >= 5:
                break
    return catalysts[:5]


def _pick_strategies(intel: dict, backtest: dict) -> list[str]:
    """Pick top 2-3 strategies based on regime."""
    regime = intel.get("regime_hint", "neutral")
    if regime == "risk_off":
        return ["short_strangle", "iron_condor"]  # premium selling, defined risk
    if regime == "risk_on":
        return ["bull_call_vertical", "iron_condor"]
    # neutral
    return ["iron_condor", "short_strangle"]


def _derive_posture(intel: dict, macro_soon: bool, paper: dict) -> tuple[str, float, bool]:
    """Return (posture, max_risk_pct, skip_first_30min)."""
    regime = intel.get("regime_hint", "neutral")
    gap = intel.get("india_open_gap_signal", "flat")
    realized = paper.get("realized_pnl", 0)
    cash = paper.get("cash", 0)
    # Drawdown check (vs initial 100k)
    initial = 100000
    drawdown_pct = max(0, (initial - (cash + realized)) / initial * 100) if cash else 0
    # Rule stack
    if drawdown_pct > 5:
        return "conservative", 1.0, True
    if regime == "risk_off" or gap == "gap_down":
        return "conservative", 1.0, True
    if macro_soon:  # event in next 4h
        return "conservative", 1.0, True
    if regime == "risk_on" and gap == "gap_up":
        return "normal", 2.0, False
    if macro_soon is False and regime == "neutral":
        return "normal", 2.0, False
    return "normal", 1.5, True


def main() -> dict:
    intel = _load_json(INTEL_PATH)
    backtest = _load_json(BACKTEST_PATH)
    paper = _load_json(STATE_PATH)

    if not intel:
        logger.error("weekend_intel.json missing — run weekend_intel.py first")
        sys.exit(1)

    cal = MacroCalendar()
    macro_events = cal.events
    # Filter to future events (within next 7 days)
    ist_now = datetime.now()
    upcoming = []
    for e in macro_events:
        try:
            dt = e["datetime_ist"]
        except KeyError:
            continue
        if dt > ist_now and (dt - ist_now).days <= 7:
            upcoming.append(e)
    # In next 4h
    macro_4h = [e for e in upcoming if 0 <= (e["datetime_ist"] - ist_now).total_seconds() / 3600 <= 4
                and e.get("importance", 0) >= 3]
    macro_blackout_soon = len(macro_4h) > 0
    macro_blackout_event = macro_4h[0] if macro_blackout_soon else None

    risks = _derive_key_risks(intel, upcoming)
    catalysts = _derive_key_catalysts(intel, upcoming)
    posture, max_risk, skip_30 = _derive_posture(intel, macro_blackout_soon, paper)
    strategies = _pick_strategies(intel, backtest)

    # Build summary
    summary_parts = []
    regime = intel.get("regime_hint", "neutral")
    gap = intel.get("india_open_gap_signal", "flat")
    summary_parts.append(f"Regime: {regime}, Gap: {gap}")
    nifty = intel.get("markets", {}).get("NIFTY", {}).get("last")
    if nifty:
        summary_parts.append(f"NIFTY: {nifty:.0f}")
    summary_parts.append(f"Posture: {posture} (max risk {max_risk}%)")
    weekend_summary = " · ".join(summary_parts)

    next_open = _next_monday_open_ist(ist_now)

    # Rationale
    rationale = []
    rationale.append(f"regime_hint={regime} → {'conservative' if regime=='risk_off' else 'normal/aggressive'}")
    rationale.append(f"gap_signal={gap} → {'skip 30min' if gap!='flat' else 'normal entry'}")
    if macro_blackout_soon:
        rationale.append(f"macro_event_4h={macro_blackout_event['name']} → conservative")
    if intel.get("markets", {}).get("WTI_CRUDE", {}).get("change_5d_pct", 0) > 2:
        rationale.append("crude +3% → India import bill risk")

    brief = {
        "as_of": ist_now.isoformat(),
        "next_session_open_ist": next_open.isoformat(),
        "weekend_summary": weekend_summary,
        "key_risks": risks,
        "key_catalysts": catalysts,
        "regime_hint": regime,
        "india_open_gap_signal": gap,
        "macro_blackout_soon": macro_blackout_soon,
        "macro_blackout_event": (
            {**macro_blackout_event, "datetime_ist": macro_blackout_event["datetime_ist"].isoformat()}
            if macro_blackout_event else None
        ),
        "macro_events_next_7d": [
            {**e, "datetime_ist": e["datetime_ist"].isoformat()}
            for e in upcoming
            if e.get("importance", 0) >= 2
        ],
        "recommended_posture": posture,
        "max_risk_per_trade_pct": max_risk,
        "skip_first_30min": skip_30,
        "preferred_strategies": strategies,
        "rationale": " | ".join(rationale),
        "nifty_last_close": intel.get("markets", {}).get("NIFTY", {}).get("last"),
        "banknifty_last_close": intel.get("markets", {}).get("BANKNIFTY", {}).get("last"),
        "india_vix": intel.get("markets", {}).get("INDIA_VIX", {}).get("last"),
        "usdinr": intel.get("markets", {}).get("USDINR", {}).get("last"),
        "wti_crude_5d_pct": intel.get("markets", {}).get("WTI_CRUDE", {}).get("change_5d_pct"),
        "sp500_5d_pct": intel.get("markets", {}).get("SP500", {}).get("change_5d_pct"),
        "intel_source_as_of": intel.get("as_of"),
        "news_count": intel.get("news_count", 0),
    }

    OUTPUT_PATH.write_text(json.dumps(brief, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"wrote {OUTPUT_PATH} ({OUTPUT_PATH.stat().st_size} bytes)")
    print(f"[monday_brief] posture={posture} risk={max_risk}% skip30={skip_30} regime={regime} gap={gap} "
          f"risks={len(risks)} catalysts={len(catalysts)} macro_blackout_4h={macro_blackout_soon}")
    return brief


if __name__ == "__main__":
    main()
