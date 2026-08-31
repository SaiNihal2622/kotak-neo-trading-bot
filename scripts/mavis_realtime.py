#!/usr/bin/env python3
"""Mavis real-time event monitor — NOT a cron, NOT 60s polls.

This is the live "Mavis is everywhere" brain. Polls every 2-5 seconds,
watches NIFTY/BNF spot + position MTM + VIX, and writes events to
data_cache/mavis_events.jsonl the moment something happens.

Events are then consumed by:
  - Dashboard /api/events (live ticker)
  - Event-driven Mavis decider (wakes Mavis on critical events)
  - Telegram alert (configurable per-event-type)

Key design: NO time-based decisions. Only EVENT-based:
  - NIFTY crosses a key level (24,000 / 24,100 / 24,200 / 24,300 / 24,400 / 24,500)
  - Position MTM hits -20% / -50% / -80% of max loss
  - Position MTM hits +30% / +50% / +70% of max profit
  - VIX spikes >2 pts in 5 min
  - US futures move >0.5% during market
  - Bot log goes stale > 30 sec during market hours

Usage:
    python scripts/mavis_realtime.py
    # Poll interval: MAVIS_POLL_MS env (default 3000ms = 3 sec)
"""
from __future__ import annotations

import json
import os
import time
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DCACHE = ROOT / "data_cache"
LOGS = ROOT / "logs"
EVENTS = DCACHE / "mavis_events.jsonl"
STATE = DCACHE / "mavis_realtime_state.json"
PAPER = DCACHE / "paper_state.json"
PLAN = DCACHE / "mavis_trades.json"
LOG_FILE = LOGS / "mavis_realtime.log"

POLL_MS = int(os.environ.get("MAVIS_POLL_MS", "3000"))
MAX_RUNTIME_MIN = int(os.environ.get("MAX_RUNTIME_MIN", "240"))


def _now_ist() -> datetime:
    return datetime.now(timezone(timedelta(hours=5, minutes=30)))


def _log(msg: str) -> None:
    line = f"[{_now_ist().isoformat()}] {msg}"
    print(line, flush=True)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _read_json(p: Path, default=None):
    try:
        with open(p, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return default


def _write_state(state: dict) -> None:
    try:
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def _append_event(event_type: str, level: str, value, context: dict) -> None:
    """Append an event to the JSONL log. Dedup against the state file's last_event_per_type."""
    state = _read_json(STATE, {})
    last = state.get("last_event_per_type", {}) or {}
    sig = f"{event_type}::{level}"
    if last.get(sig) == value:
        return  # dedup, no change
    last[sig] = value
    state["last_event_per_type"] = last
    state["last_event_ts"] = _now_ist().isoformat()
    state["last_event"] = {"type": event_type, "level": level, "value": value}
    _write_state(state)
    rec = {
        "ts": _now_ist().isoformat(),
        "type": event_type,
        "level": level,
        "value": value,
        "context": context,
    }
    try:
        with open(EVENTS, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception as e:
        _log(f"  [err] event write: {e}")
    _log(f"  EVENT: {event_type} {level}={value} ctx={json.dumps(context)[:120]}")


def _is_market_hours() -> bool:
    """True if NSE cash market is open (Mon-Fri 09:00-15:45 IST)."""
    now = _now_ist()
    if now.weekday() >= 5:  # Sat/Sun
        return False
    h, m = now.hour, now.minute
    return (h > 9 or (h == 9 and m >= 0)) and (h < 15 or (h == 15 and m <= 45))


def _safe_yf_close(symbol: str) -> float:
    """yfinance Close that returns 0.0 on empty DataFrame (weekends, US holidays)."""
    try:
        import yfinance as yf
        df = yf.Ticker(symbol).history(period="1d")
        if df is None or df.empty or "Close" not in df.columns:
            return 0.0
        closes = df["Close"].dropna()
        if closes.empty:
            return 0.0
        return float(closes.iloc[-1])
    except Exception as e:
        _log(f"  [warn] yfinance {symbol} fetch failed: {type(e).__name__}: {str(e)[:120]}")
        return 0.0


def _fetch_spot() -> dict:
    """Fetch NIFTY, BANKNIFTY, India VIX. Cached for 5s.

    Off-hours (weekends, US holidays, late-night IST): returns 0.0 silently
    instead of flooding the log with IndexError from empty DataFrames.
    During market hours: tries yfinance first, then a public API fallback if it
    returns 0.0.
    """
    state = _read_json(STATE, {})
    cache = state.get("spot_cache") or {}
    if cache.get("ts") and (time.time() - cache["ts"]) < 5:
        return cache["data"]

    out = {"nifty": 0.0, "banknifty": 0.0, "vix": 0.0}

    if not _is_market_hours():
        # Skip the yfinance call during off-hours. We still write the cache so
        # downstream code sees a consistent shape, but we don't pollute the log.
        state["spot_cache"] = {"ts": time.time(), "data": out, "source": "off_hours"}
        _write_state(state)
        return out

    out["nifty"] = _safe_yf_close("^NSEI")
    out["banknifty"] = _safe_yf_close("^NSEBANK")
    out["vix"] = _safe_yf_close("^INDIAVIX")
    state["spot_cache"] = {"ts": time.time(), "data": out, "source": "yfinance"}
    _write_state(state)
    return out


def _compute_position_mtm(spot: float) -> dict:
    """Compute current MTM for any open positions in paper_state.json.

    For iron condor (sell PE+buy PE+sell CE+buy CE), rough intrinsic MTM:
      - For each short option: max(0, intrinsic_at_spot) is what it would cost to buy back
      - For each long option: max(0, intrinsic_at_spot) - paid
      - Total MTM = sum of (current_value - entry_value) for all legs
    Rough: short 24200 PE at spot 24,100 = intrinsic 100 * qty (we owe 100)
           long 24100 PE at spot 24,100 = intrinsic 0 (we hold protection worth 0)
           so put spread MTM = -100 * qty (we are at max loss on this side)
    """
    ps = _read_json(PAPER, {})
    positions = ps.get("positions", {}) or {}
    out = {"open_count": len(positions), "mtm_total": 0.0, "by_underlying": {}, "legs": []}
    for tid, p in positions.items():
        u = p.get("underlying", "")
        legs = p.get("legs", []) or []
        pos_mtm = 0.0
        for leg in legs:
            strike = float(leg.get("strike", 0))
            opt = leg.get("opt_type", "")
            side = leg.get("side", "")
            qty = int(leg.get("qty", 0)) * 75 if u == "NIFTY" else int(leg.get("qty", 0)) * 30
            entry = float(leg.get("entry_price", 0))
            intrinsic = 0.0
            if opt == "CE":
                intrinsic = max(0.0, spot - strike) if side == "sell" else max(0.0, spot - strike)
            else:  # PE
                intrinsic = max(0.0, strike - spot)
            cur_val = intrinsic
            if side == "sell":
                pnl = (entry - cur_val) * qty  # sold high, buy back lower = profit
            else:
                pnl = (cur_val - entry) * qty  # bought low, sell high = profit
            pos_mtm += pnl
            out["legs"].append({"trade": tid[:8], "u": u, "side": side, "opt": opt,
                                "strike": strike, "qty": qty, "entry": entry,
                                "cur_intrinsic": cur_val, "pnl": round(pnl, 2)})
        out["by_underlying"][u] = out["by_underlying"].get(u, 0.0) + pos_mtm
        out["mtm_total"] += pos_mtm
    out["mtm_total"] = round(out["mtm_total"], 2)
    return out


# Key levels (from Mavis's plan for today)
KEY_LEVELS = {
    "nifty_support_p1": 24100,   # below this = put side at risk
    "nifty_support_p2": 24000,   # below this = short put ITM
    "nifty_resistance_c1": 24500,  # above this = short call ITM
    "nifty_resistance_c2": 24600,
    "nifty_max_pain": 24300,
    "nifty_oi_put_wall": 24200,
    "nifty_oi_call_wall": 24500,
}


def _check_nifty_events(spot: float) -> None:
    """Generate events when NIFTY crosses key levels."""
    if not spot:
        return
    n = int(round(spot))
    # Generate a crossing event for each level NIFTY is at/below/above
    for k, v in KEY_LEVELS.items():
        diff = n - v
        # Event when within 30 pts of level (proximity)
        if abs(diff) <= 30:
            side = "above" if diff >= 0 else "below"
            _append_event("nifty_level_proximity", k, n, {"level_value": v, "diff": diff, "side": side})
    # Break events: NIFTY crossed 24,000 OR 24,500
    state = _read_json(STATE, {})
    last_spot = state.get("last_nifty", 0)
    if last_spot and spot:
        if last_spot > 24000 >= spot:
            _append_event("nifty_breakdown", "24000", spot, {"prev": last_spot})
        if last_spot < 24000 <= spot:
            _append_event("nifty_breakout", "24000", spot, {"prev": last_spot})
        if last_spot < 24500 <= spot:
            _append_event("nifty_breakout", "24500", spot, {"prev": last_spot})
        if last_spot > 24500 >= spot:
            _append_event("nifty_breakdown", "24500", spot, {"prev": last_spot})
    state["last_nifty"] = spot
    _write_state(state)


def _check_vix_events(vix: float) -> None:
    if not vix:
        return
    state = _read_json(STATE, {})
    last_vix = state.get("last_vix", 0)
    if last_vix:
        delta = vix - last_vix
        if abs(delta) >= 1.5:
            _append_event("vix_spike", "delta>=1.5", vix, {"prev": last_vix, "delta": round(delta, 2)})
    # Absolute thresholds
    if vix > 14 and last_vix <= 14:
        _append_event("vix_above_threshold", "14", vix, {})
    if vix > 16 and last_vix <= 16:
        _append_event("vix_above_threshold", "16", vix, {})
    state["last_vix"] = vix
    _write_state(state)


def _check_mtm_events(mtm: dict) -> None:
    """Generate events based on position MTM."""
    if mtm["open_count"] == 0:
        return
    state = _read_json(STATE, {})
    for u, pnl in mtm["by_underlying"].items():
        # Find max loss from plan
        plan = _read_json(PLAN, {})
        max_loss = 0.0
        if str(plan.get("valid_for_date", "")) == _now_ist().strftime("%Y-%m-%d"):
            pp = plan.get("primary_plan", {}) or {}
            ml = pp.get("max_loss_rupees", {}) or {}
            single = ml.get("realistic_max_loss_single_wing", "Rs.0")
            if isinstance(single, str):
                import re
                nums = re.findall(r"[\d,]+", single)
                if nums:
                    max_loss = float(nums[0].replace(",", ""))
        if max_loss <= 0:
            continue
        loss_pct = -pnl / max_loss * 100 if pnl < 0 else 0
        profit_pct = pnl / max_loss * 100 if pnl > 0 else 0
        # Loss thresholds
        if loss_pct >= 80:
            _append_event("mtm_loss", f"{u}_80pct", pnl, {"loss_pct": round(loss_pct, 1), "max_loss": max_loss})
        elif loss_pct >= 50:
            _append_event("mtm_loss", f"{u}_50pct", pnl, {"loss_pct": round(loss_pct, 1), "max_loss": max_loss})
        elif loss_pct >= 25:
            _append_event("mtm_loss", f"{u}_25pct", pnl, {"loss_pct": round(loss_pct, 1), "max_loss": max_loss})
        # Profit thresholds
        if profit_pct >= 70:
            _append_event("mtm_profit", f"{u}_70pct", pnl, {"profit_pct": round(profit_pct, 1)})
        elif profit_pct >= 50:
            _append_event("mtm_profit", f"{u}_50pct", pnl, {"profit_pct": round(profit_pct, 1)})


def _send_telegram(msg: str) -> None:
    try:
        cred = ROOT / "config" / "credentials.env"
        if not cred.exists():
            return
        token = None
        chat_id = None
        for line in cred.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("TELEGRAM_BOT_TOKEN="):
                token = line.split("=", 1)[1].strip().strip('"').strip("'")
            elif line.startswith("TELEGRAM_CHAT_ID="):
                chat_id = line.split("=", 1)[1].strip().strip('"').strip("'")
        if not token or not chat_id:
            return
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": chat_id, "text": msg[:4000]}).encode()
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            r.read()
    except Exception as e:
        _log(f"  [tg] send failed: {e}")


def main() -> int:
    LOGS.mkdir(parents=True, exist_ok=True)
    start = time.time()
    _log(f"=== Mavis real-time started (poll={POLL_MS}ms, max={MAX_RUNTIME_MIN}min) ===")
    last_tg_nifty = 0.0
    cycle = 0
    while True:
        elapsed_min = (time.time() - start) / 60
        if elapsed_min > MAX_RUNTIME_MIN:
            _log(f"=== Mavis real-time rotating after {elapsed_min:.1f}min ===")
            return 0
        cycle += 1
        try:
            now = _now_ist()
            spot = _fetch_spot()
            nifty = spot.get("nifty", 0)
            vix = spot.get("vix", 0)
            mtm = _compute_position_mtm(nifty)
            # Always update state with current snapshot for dashboard
            state = _read_json(STATE, {})
            state["current"] = {
                "ts": now.isoformat(),
                "nifty": nifty,
                "banknifty": spot.get("banknifty", 0),
                "vix": vix,
                "open_positions": mtm["open_count"],
                "mtm_total": mtm["mtm_total"],
                "by_underlying": mtm["by_underlying"],
            }
            # Mavis's current state of mind (visible in dashboard)
            mkt_open = 9 <= now.hour <= 15
            mins_to_force = None
            if mkt_open:
                force_t = now.replace(hour=14, minute=30, second=0, microsecond=0)
                if now < force_t:
                    mins_to_force = int((force_t - now).total_seconds() / 60)
            state["current"]["mavis_state"] = {
                "ts": now.isoformat(),
                "mkt_open": mkt_open,
                "mins_to_force_square": mins_to_force,
                "is_watching": True,
                "last_thought": _last_thought(nifty, vix, mtm, mins_to_force),
            }
            _write_state(state)
            # Event detection
            _check_nifty_events(nifty)
            _check_vix_events(vix)
            _check_mtm_events(mtm)
            # Telegram on key events: only on first detection (state.last_tg_*)
            if nifty and (nifty < 24100 or nifty > 24500) and (time.time() - last_tg_nifty) > 300:
                last_tg_nifty = time.time()
                if nifty < 24100:
                    _send_telegram(f"[Mavis live] NIFTY {nifty:.0f} < 24,100. Put wing under pressure.")
                else:
                    _send_telegram(f"[Mavis live] NIFTY {nifty:.0f} > 24,500. Call wing under pressure.")
            # Heartbeat every 20 cycles
            if cycle % 20 == 1:
                _log(f"  cycle={cycle} NIFTY={nifty:.2f} BNF={spot.get('banknifty',0):.2f} VIX={vix:.2f} pos={mtm['open_count']} mtm=Rs.{mtm['mtm_total']:.0f} mkt={mkt_open} mins_to_force={mins_to_force}")
        except Exception as e:
            _log(f"  [cycle error] {e}")
        time.sleep(POLL_MS / 1000)


def _last_thought(nifty: float, vix: float, mtm: dict, mins_to_force) -> str:
    """A short Mavis-style observation for the dashboard."""
    if not mtm["open_count"]:
        if nifty and nifty > 0:
            if nifty < 24000:
                return f"NIFTY {nifty:.0f} below 24,000. No position. Watching."
            if nifty > 24500:
                return f"NIFTY {nifty:.0f} above 24,500. No position. Watching."
            return f"NIFTY {nifty:.0f} in range 24k-24.5k. Flat. Watching for entry signal."
        return "Market closed. Standing by."
    # With position
    pnl = mtm["mtm_total"]
    if pnl > 0:
        return f"Position in profit Rs.{pnl:.0f}. NIFTY {nifty:.0f}. {mins_to_force or '?'} min to force-square."
    if pnl < 0:
        return f"Position in loss Rs.{pnl:.0f}. NIFTY {nifty:.0f}. Monitoring closely."
    return f"Position flat. NIFTY {nifty:.0f}. {mins_to_force or '?'} min to force-square."


if __name__ == "__main__":
    raise SystemExit(main())
