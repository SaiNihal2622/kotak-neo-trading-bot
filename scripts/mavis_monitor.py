#!/usr/bin/env python3
"""Mavis 24/7 monitor — runs continuously in a background task.

Watches:
  - Bot health (paper_state.json changes, liveness.json freshness, log errors)
  - Market state (NIFTY/BANKNIFTY spot via yfinance every 5 min)
  - Trade plan (mavis_trades.json valid_for today? action still valid?)
  - Dashboard ports (:8501, :8502, :8504)

On material change:
  - Updates mavis_trades.json with intraday decision changes
  - Sends Telegram alert via bot token from config/credentials.env
  - Appends to logs/mavis_monitor.log

Auto-rotates every 4 hours by exiting cleanly (the wrapper cron respawns).

Usage:
    python scripts/mavis_monitor.py
    # Or set MAX_RUNTIME_MIN=240 to rotate after 4h.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DCACHE = ROOT / "data_cache"
LOGS = ROOT / "logs"
PLAN = DCACHE / "mavis_trades.json"
PAPER = DCACHE / "paper_state.json"
LIVENESS = DCACHE / "liveness.json"
LOG_FILE = LOGS / "mavis_monitor.log"

# How long this instance runs before cleanly exiting (so the wrapper can respawn)
MAX_RUNTIME_MIN = int(os.environ.get("MAX_RUNTIME_MIN", "240"))
POLL_SEC = int(os.environ.get("POLL_SEC", "60"))


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


def _send_telegram(msg: str) -> None:
    """Send a Telegram message via the bot token in credentials.env.

    Best-effort: any error is logged but never raised (we don't want the
    monitor loop to die because Telegram is flaky).
    """
    try:
        import urllib.request
        import urllib.parse
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


def _fetch_spot() -> tuple[float, float, float]:
    """Best-effort NIFTY spot, BANKNIFTY spot, India VIX via yfinance."""
    try:
        import yfinance as yf
        n = float(yf.Ticker("^NSEI").history(period="1d")["Close"].iloc[-1])
        b = float(yf.Ticker("^NSEBANK").history(period="1d")["Close"].iloc[-1])
        v = float(yf.Ticker("^INDIAVIX").history(period="1d")["Close"].iloc[-1])
        return n, b, v
    except Exception as e:
        _log(f"  [warn] yfinance fetch failed: {e}")
        return 0.0, 0.0, 0.0


def _check_bot_health() -> dict:
    """Quick health check on bot + dashboards + log."""
    health = {
        "ts": _now_ist().isoformat(),
        "bot_liveness_age_sec": None,
        "dashboard_8501": False,
        "dashboard_8502": False,
        "dashboard_8504": False,
        "log_size": 0,
        "log_mtime": None,
        "open_positions": 0,
        "cash": 0.0,
        "realized_pnl": 0.0,
    }
    if LIVENESS.exists():
        try:
            age = time.time() - LIVENESS.stat().st_mtime
            health["bot_liveness_age_sec"] = round(age, 1)
        except Exception:
            pass
    if PAPER.exists():
        try:
            ps = _read_json(PAPER, {})
            health["open_positions"] = len(ps.get("positions", {}) or {})
            health["cash"] = float(ps.get("cash", 0))
            health["realized_pnl"] = float(ps.get("realized_pnl", 0))
        except Exception:
            pass
    bot_log = LOGS / "bot.log"
    if bot_log.exists():
        try:
            st = bot_log.stat()
            health["log_size"] = st.st_size
            health["log_mtime"] = _now_ist().isoformat()
        except Exception:
            pass
    # Check dashboards
    try:
        import urllib.request
        for port in (8501, 8502, 8504):
            try:
                with urllib.request.urlopen(f"http://localhost:{port}/", timeout=2) as r:
                    health[f"dashboard_{port}"] = r.status == 200
            except Exception:
                health[f"dashboard_{port}"] = False
    except Exception:
        pass
    return health


def _maybe_update_plan(spot: float, vix: float, health: dict) -> str | None:
    """If Mavis's plan is still valid for today but conditions have changed
    intraday, flip to BLOCK or apply adjustment. Returns a Telegram alert
    string if a change was made, else None.
    """
    if not PLAN.exists():
        return None
    plan = _read_json(PLAN, {})
    today = _now_ist().strftime("%Y-%m-%d")
    valid_for = plan.get("valid_for_date") or ""
    if today not in str(valid_for):
        return None
    decision = plan.get("mavis_decision") or {}
    action = str(decision.get("action", "")).upper()
    if action != "EXECUTE_PLAN":
        return None
    # Check intraday trip conditions
    primary = plan.get("primary_plan") or {}
    entry = primary.get("entry_signal", {}) or {}
    conds = entry.get("conditions_all_required", [])
    alerts = []
    # NIFTY broke below 24,000 (alt 1 trigger)
    if 0 < spot < 24000:
        decision["action"] = "BLOCK"
        decision["reason_short"] = (
            f"Mavis intraday BLOCK: NIFTY broke below 24,000 (now {spot:.0f}). "
            f"Per alt_1 trigger. Existing condor would be at risk; safer to skip."
        )
        plan["mavis_decision"] = decision
        plan["last_decision_at"] = _now_ist().isoformat()
        try:
            with open(PLAN, "w", encoding="utf-8") as f:
                json.dump(plan, f, indent=2, ensure_ascii=False)
            alerts.append(f"[Mavis intraday] BLOCK at {spot:.0f} < 24,000. Plan flipped to NO TRADE.")
        except Exception as e:
            _log(f"  [err] plan write failed: {e}")
    # NIFTY ran above 24,500 (alt 1 mirror)
    elif spot > 24500:
        decision["action"] = "BLOCK"
        decision["reason_short"] = (
            f"Mavis intraday BLOCK: NIFTY broke above 24,500 (now {spot:.0f}). "
            f"24,500 CE sold is at risk; condor max loss path widening."
        )
        plan["mavis_decision"] = decision
        plan["last_decision_at"] = _now_ist().isoformat()
        try:
            with open(PLAN, "w", encoding="utf-8") as f:
                json.dump(plan, f, indent=2, ensure_ascii=False)
            alerts.append(f"[Mavis intraday] BLOCK at {spot:.0f} > 24,500. Condor risk too high.")
        except Exception as e:
            _log(f"  [err] plan write failed: {e}")
    # VIX spike (cheap premium gone, vol shock)
    elif vix > 15:
        decision["action"] = "BLOCK"
        decision["reason_short"] = (
            f"Mavis intraday BLOCK: VIX spiked to {vix:.1f} (>15 threshold). "
            f"Vol shock invalidates cheap-premium thesis."
        )
        plan["mavis_decision"] = decision
        plan["last_decision_at"] = _now_ist().isoformat()
        try:
            with open(PLAN, "w", encoding="utf-8") as f:
                json.dump(plan, f, indent=2, ensure_ascii=False)
            alerts.append(f"[Mavis intraday] BLOCK: VIX spike to {vix:.1f}.")
        except Exception as e:
            _log(f"  [err] plan write failed: {e}")
    if alerts:
        return "\n".join(alerts)
    return None


def main() -> int:
    LOGS.mkdir(parents=True, exist_ok=True)
    start = time.time()
    _log(f"=== Mavis monitor started (max_runtime={MAX_RUNTIME_MIN}min, poll={POLL_SEC}s) ===")
    last_spot = 0.0
    last_vix = 0.0
    last_dash_alert = 0.0
    last_health = None
    cycle = 0
    while True:
        elapsed_min = (time.time() - start) / 60
        if elapsed_min > MAX_RUNTIME_MIN:
            _log(f"=== Mavis monitor rotating after {elapsed_min:.1f}min ===")
            return 0
        cycle += 1
        try:
            now = _now_ist()
            # Skip market-closed heavy checks at night (still run health check)
            nifty, banknifty, vix = _fetch_spot()
            health = _check_bot_health()
            # Log every 5th cycle (5 min if poll=60)
            if cycle % 5 == 1 or cycle == 1:
                _log(
                    f"cycle={cycle} NIFTY={nifty:.2f} BNF={banknifty:.2f} VIX={vix:.2f} "
                    f"dash[8501={health['dashboard_8501']}/8502={health['dashboard_8502']}/"
                    f"8504={health['dashboard_8504']}] log={health['log_size']}B "
                    f"pos={health['open_positions']} cash=Rs.{health['cash']:.0f} "
                    f"realized=Rs.{health['realized_pnl']:.0f}"
                )
            # Detect material change in spot
            if nifty > 0 and last_spot > 0 and abs(nifty - last_spot) > 50:
                _log(f"  NIFTY moved {nifty - last_spot:+.0f} pts since last check")
            last_spot = nifty
            last_vix = vix
            # Update intraday plan if conditions breach
            if nifty > 0 and vix > 0:
                alert = _maybe_update_plan(nifty, vix, health)
                if alert:
                    _log(f"  ALERT: {alert[:200]}")
                    _send_telegram(alert)
            # Detect dashboard down (alert at most once per 30 min)
            down_dash = [p for p in (8501, 8502, 8504) if not health[f"dashboard_{p}"]]
            if down_dash and (time.time() - last_dash_alert) > 1800:
                last_dash_alert = time.time()
                msg = f"[Mavis 24/7] Dashboard DOWN on :{', :'.join(map(str, down_dash))}. Bot may still be alive but UI is broken."
                _log(f"  ALERT: {msg}")
                _send_telegram(msg)
            # Detect bot log stale (no write in 5 min during market hours)
            if health["log_size"] and health["log_mtime"]:
                age = time.time() - LIVENESS.stat().st_mtime if LIVENESS.exists() else 999
                if 9 <= now.hour <= 15 and age > 300:  # 5 min
                    if last_health is None or last_health.get("bot_liveness_age_sec", 0) <= 300:
                        msg = f"[Mavis 24/7] Bot log stale {age:.0f}s during market hours. Possible hang."
                        _log(f"  ALERT: {msg}")
                        _send_telegram(msg)
            last_health = health
        except Exception as e:
            _log(f"  [cycle error] {e}")
        time.sleep(POLL_SEC)


if __name__ == "__main__":
    raise SystemExit(main())
