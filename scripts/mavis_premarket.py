#!/usr/bin/env python3
"""Mavis pre-market refresher.

Reads current data_cache/mavis_trades.json, refreshes the research section
with fresh pre-market data (US close, India VIX, spot price, FII/DII flows
already in mavis_trades.json), applies the entry-signal conditions, and
either confirms EXECUTE_PLAN or flips to BLOCK.

Run by cron at 08:35 IST on trading days.

Usage:
    python scripts/mavis_premarket.py
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DCACHE = ROOT / "data_cache"
PLAN_PATH = DCACHE / "mavis_trades.json"
LOG_PATH = ROOT / "logs" / "mavis_premarket.log"


def _now_ist() -> datetime:
    return datetime.now(timezone(timedelta(hours=5, minutes=30)))


def _fetch_spot_and_vix() -> tuple[float, float]:
    """Best-effort: yfinance for NIFTY spot + India VIX."""
    try:
        import yfinance as yf
        nifty = yf.Ticker("^NSEI")
        spot = float(nifty.history(period="1d")["Close"].iloc[-1])
        vix_t = yf.Ticker("^INDIAVIX")
        vix = float(vix_t.history(period="1d")["Close"].iloc[-1])
        return spot, vix
    except Exception as e:
        print(f"  [warn] yfinance fetch failed: {e}", file=sys.stderr)
        return 0.0, 0.0


def _fetch_us_futures_change() -> dict[str, float]:
    """Best-effort: ES, NQ, YM futures change %."""
    try:
        import yfinance as yf
        out = {}
        for sym, key in [("ES=F", "spx_fut"), ("NQ=F", "nasdaq_fut"), ("YM=F", "dow_fut")]:
            t = yf.Ticker(sym)
            hist = t.history(period="2d")
            if len(hist) >= 2:
                chg = (float(hist["Close"].iloc[-1]) / float(hist["Close"].iloc[-2]) - 1) * 100
                out[key] = round(chg, 2)
        return out
    except Exception as e:
        print(f"  [warn] us futures fetch failed: {e}", file=sys.stderr)
        return {}


def main() -> int:
    now = _now_ist()
    today_str = now.strftime("%Y-%m-%d")
    print(f"[{now.isoformat()}] Mavis pre-market refresh starting for {today_str}")

    if not PLAN_PATH.exists():
        print(f"  [err] {PLAN_PATH} not found", file=sys.stderr)
        return 1
    try:
        with open(PLAN_PATH, "r", encoding="utf-8-sig") as f:
            plan = json.load(f)
    except Exception as e:
        print(f"  [err] plan parse failed: {e}", file=sys.stderr)
        return 2

    if plan.get("valid_for_date") != today_str:
        # Stale plan (from a previous day). Update valid_for_date and refresh —
        # the existing plan structure (primary_plan, strategy) is reusable; we're
        # just re-running the conditions check against today's market state.
        plan["valid_for_date"] = today_str
        plan["valid_for_session"] = f"{now.strftime('%a %d-%b-%Y')} NSE regular session"
        print(f"  [info] plan valid_for={plan.get('valid_for_date')}, today={today_str}. refreshing stale plan.")

    # Refresh research
    spot, vix = _fetch_spot_and_vix()
    us_fut = _fetch_us_futures_change()
    research = plan.get("research_at_generation", {})

    if spot > 0:
        research["nifty_spot"] = round(spot, 2)
    if vix > 0:
        research["india_vix"] = round(vix, 2)
    if us_fut:
        # build a short summary string
        research["us_futures_overnight"] = ", ".join(
            f"{k}={v:+.2f}%" for k, v in us_fut.items()
        )
    research["refreshed_at"] = now.isoformat()
    plan["research_at_generation"] = research
    plan["last_refresh_at"] = now.isoformat()

    # Apply entry-signal conditions to make the final decision
    primary = plan.get("primary_plan", {}) or {}
    entry = primary.get("entry_signal", {}) or {}
    conds = entry.get("conditions_all_required", [])
    decision = plan.get("mavis_decision", {}) or {}

    # Spot range check
    cur_spot = research.get("nifty_spot", 0)
    in_range = 24000 <= cur_spot <= 24500 if cur_spot else False

    # US futures check (max abs change)
    max_us_chg = 0.0
    for v in us_fut.values():
        if abs(v) > abs(max_us_chg):
            max_us_chg = v
    us_calm = abs(max_us_chg) < 0.4

    # VIX check
    vix_ok = 0 < vix < 12

    # ARCHITECTURE FIX 2026-09-01: LLM brain (quant_service.py) is the SOLE decision
    # authority. The Mavis pre-market plan is now CONTEXT-ONLY — its research,
    # bias, and market view are still valuable for the LLM brain to read, but
    # the bot's Mavis plan execution path is disabled by always setting
    # action=BLOCK. The bot will see BLOCK and not attempt to trade on this.
    decision["action"] = "BLOCK"
    decision["reason_short"] = (
        f"Mavis pre-market CONTEXT ONLY (LLM brain is sole decision authority): "
        f"spot={cur_spot}, us_max_chg={max_us_chg:+.2f}%, vix={vix}, "
        f"in_range={in_range}, us_calm={us_calm}, vix_ok={vix_ok}. "
        f"See data_cache/mavis_trades.json for research context."
    )
    plan["premarket_check"] = {
        "spot_in_range": in_range, "us_calm": us_calm, "vix_ok": vix_ok,
        "context_only": True, "decision_authority": "quant_service.py LLM brain",
    }

    plan["mavis_decision"] = decision
    plan["last_decision_at"] = now.isoformat()

    try:
        with open(PLAN_PATH, "w", encoding="utf-8") as f:
            json.dump(plan, f, indent=2, ensure_ascii=False)
        print(f"  [ok] wrote {PLAN_PATH}")
    except Exception as e:
        print(f"  [err] write failed: {e}", file=sys.stderr)
        return 3

    # Log
    DCACHE.mkdir(parents=True, exist_ok=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(
            f"[{now.isoformat()}] {decision['action']:14s} spot={cur_spot} vix={vix} "
            f"us_max_chg={max_us_chg:+.2f}% reason={decision['reason_short'][:120]}\n"
        )
    print(f"  [done] decision={decision['action']}, reason={decision['reason_short'][:140]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
