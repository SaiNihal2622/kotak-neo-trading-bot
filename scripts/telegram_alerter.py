"""telegram_alerter.py — rich Telegram notifications for the quant brain.

The bot's existing `TelegramAlerter` (in kotak_bot.alerts.telegram) handles
trade-confirmations. This module adds the *brain-side* notifications that
the LLM-driven quant_service needs:

  - LLM DECISION: every HOLD/OPEN/CLOSE the brain makes, with rationale
  - POSITION UPDATE: every N minutes while position is open
  - RISK ALERT: drawdown, circuit breaker, error
  - OI ALERT: significant OI build-up/unwinding (>15%)
  - DAILY SUMMARY: at 15:30 IST (post-market)
  - HEARTBEAT: every 4h during market hours (one-line status)

Throttling:
  - Max 1 message per category per N seconds (configurable)
  - Forced alerts (RISK_ALERT) bypass throttling
  - Dedup: if a message has been sent in the last 5min, skip

Wired into:
  - quant_service: after every invoke_llm_decision
  - quant_service: every main loop iteration (heartbeat / OI alert)
  - (Optional) kotak_bot.__main__: for risk alerts

Usage:
    from telegram_alerter import get_alerter
    a = get_alerter()
    a.decision_made({"type": "OPEN", "underlying": "NIFTY", "strategy": "iron_condor",
                     "rationale": "...", "max_hold_minutes": 240, "target": 6000, "stop": 3000})
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
DATA = ROOT / 'data_cache'
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

# Throttle: min seconds between same-category messages
DEFAULT_THROTTLE = {
    "decision": 30,        # every LLM decision (low throttle)
    "position": 900,       # 15 min between position updates
    "risk": 60,            # 1 min between risk alerts
    "oi": 300,             # 5 min between OI alerts
    "heartbeat": 14400,    # 4h between heartbeats
    "daily": 86400,        # 1/day
    "session": 3600,       # 1h between session events
}
SENT_LOG = DATA / "telegram_sent.jsonl"


# ---------------------------------------------------------------------------
# Lazy import of the existing alerter
# ---------------------------------------------------------------------------

_alerter = None
_enabled = False


def _safe_float(x, default=0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def get_alerter():
    """Lazy-init the TelegramAlerter. Returns None if disabled."""
    global _alerter, _enabled
    if _alerter is not None:
        return _alerter
    try:
        from kotak_bot.alerts.telegram import TelegramAlerter
        _alerter = TelegramAlerter()  # reads env vars
        _enabled = _alerter.enabled
    except Exception as e:
        _alerter = None
        _enabled = False
    return _alerter


def _is_throttled(category: str, min_interval: Optional[int] = None) -> bool:
    """Check if we sent a message in this category recently."""
    min_interval = min_interval or DEFAULT_THROTTLE.get(category, 60)
    if not SENT_LOG.exists():
        return False
    cutoff = time.time() - min_interval
    try:
        with open(SENT_LOG, "r", encoding="utf-8") as f:
            for line in reversed(list(f)[-50:]):  # check last 50
                try:
                    rec = json.loads(line)
                    if rec.get("category") == category and rec.get("ts_unix", 0) > cutoff:
                        return True
                except Exception:
                    continue
    except Exception:
        return False
    return False


def _record_sent(category: str) -> None:
    try:
        with open(SENT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"category": category, "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
                                "ts_unix": time.time()}) + "\n")
    except Exception:
        pass


def _send(message: str, category: str = "decision", force: bool = False) -> bool:
    """Send a message via Telegram. Returns True if sent."""
    if not _enabled:
        return False
    if not force and _is_throttled(category):
        return False
    a = get_alerter()
    if not a:
        return False
    try:
        ok = a.send(message)
        if ok:
            _record_sent(category)
        return ok
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Public API — high-level message helpers
# ---------------------------------------------------------------------------

def decision_made(decision: dict, context: Optional[dict] = None) -> bool:
    """LLM made a decision. Send rich Telegram alert.

    Args:
        decision: {type, underlying, strategy, rationale, target, stop, max_hold_minutes, note}
        context: optional LLM context for richer alerts (backtest, macro, etc.)
    """
    if not _enabled:
        return False
    t = (decision.get("type") or "HOLD").upper()
    if t == "HOLD":
        # Don't spam on HOLD unless there's a notable note
        note = decision.get("note") or ""
        if not any(x in note for x in ["first", "circuit", "paused", "stop", "edge"]):
            return False
        msg = f"🟡 *HOLD* — `{note[:120]}`"
    elif t == "OPEN":
        u = decision.get("underlying", "?")
        s = decision.get("strategy", "?")
        rationale = (decision.get("rationale") or "")[:200]
        target = _safe_float(decision.get("target"), 0)
        stop = _safe_float(decision.get("stop"), 0)
        max_hold = decision.get("max_hold_minutes", "?")
        msg = (
            f"🟢 *OPEN {s}* on {u}\n"
            f"Target: ₹{target:,.0f}  |  Stop: ₹{stop:,.0f}  |  Hold: {max_hold}m\n"
            f"_{rationale}_\n"
        )
        # Add backtest hint if available
        if context and context.get("backtest"):
            bt = context["backtest"]
            sample = bt.get("per_strategy", {}).get(s, {})
            if sample:
                msg += f"📊 Edge: n={sample.get('n', 0)} WR={sample.get('win_rate', 0):.0%} (grade {sample.get('sample_grade', '?')})\n"
        # Add macro context
        if context and context.get("macro"):
            events = context["macro"].get("upcoming_high_impact", [])
            if events:
                ev = events[0]
                msg += f"📅 Next HIGH event: {ev.get('name', '?')} in {ev.get('days_until', '?')}d\n"
    elif t == "CLOSE":
        u = decision.get("underlying", "?")
        reason = (decision.get("reason") or decision.get("note") or "manual").replace("_", " ")
        pnl = _safe_float(decision.get("pnl"), 0)
        emoji = "✅" if pnl >= 0 else "❌"
        msg = f"{emoji} *CLOSE {u}* — {reason}  P&L: ₹{pnl:,.0f}"
    else:
        msg = f"ℹ️ {t}: {json.dumps(decision, default=str)[:200]}"

    return _send(msg, category="decision")


def position_update(positions: dict, capital: float, realized_pnl: float) -> bool:
    """Periodic position + P&L update. Throttled to 15min."""
    if not _enabled:
        return False
    if not positions:
        return False  # no positions = nothing to update
    n = len(positions)
    pos_lines = []
    for tid, p in list(positions.items())[:3]:
        u = p.get("underlying", "?")
        s = p.get("strategy", "?")
        pnl = _safe_float(p.get("pnl_estimate") or p.get("unrealized_pnl"), 0)
        held = p.get("held_minutes", 0)
        emoji = "🟢" if pnl >= 0 else "🔴"
        pos_lines.append(f"  {emoji} {u} {s}  ₹{pnl:,.0f}  ({held}m)")
    msg = (
        f"📊 *Open positions: {n}/{capital:,.0f} capital, P&L ₹{realized_pnl:,.0f}*\n"
        + "\n".join(pos_lines)
    )
    return _send(msg, category="position")


def risk_alert(reason: str, severity: str = "warning", details: Optional[dict] = None) -> bool:
    """Send a risk alert (drawdown, circuit breaker, error). Forced (no throttle)."""
    if not _enabled:
        return False
    emoji = "🚨" if severity == "critical" else "⚠️"
    msg = f"{emoji} *{severity.upper()}*: {reason}"
    if details:
        msg += "\n" + "\n".join(f"  {k}: {v}" for k, v in list(details.items())[:5])
    return _send(msg, category="risk", force=True)


def oi_alert(changes: dict, threshold_pct: float = 15.0) -> bool:
    """Send OI change alert if any strike has >threshold_pct% change."""
    if not _enabled:
        return False
    sig_bu = [b for b in changes.get("top_build_up", []) if b.get("change_pct", 0) >= threshold_pct]
    sig_uw = [u for u in changes.get("top_unwinding", []) if abs(u.get("change_pct", 0)) >= threshold_pct]
    if not sig_bu and not sig_uw:
        return False
    msg = f"🔔 *OI alert: {changes.get('underlying', '?')}* (lookback {changes.get('lookback_min', '?')}m)\n"
    for b in sig_bu[:3]:
        msg += f"  📈 Build-up {b['strike']} {b['side']}: {b['change_pct']:+.1f}% (OI={b['oi_now']:,})\n"
    for u in sig_uw[:3]:
        msg += f"  📉 Unwinding {u['strike']} {u['side']}: {u['change_pct']:+.1f}% (OI={u['oi_now']:,})\n"
    if changes.get("pcr_change"):
        msg += f"  PCR: {changes.get('pcr_prev')} → {changes.get('pcr_now')} ({changes.get('pcr_change'):+.2f})"
    return _send(msg, category="oi")


def heartbeat(state: dict) -> bool:
    """Send a periodic one-line status (every 4h during market hours)."""
    if not _enabled:
        return False
    msg = (
        f"💓 *Heartbeat* — capital ₹{state.get('capital', 0):,.0f}, "
        f"realized ₹{state.get('realized_pnl', 0):,.0f}, "
        f"open={state.get('open_positions', 0)}, "
        f"tick={state.get('tick', 0)}"
    )
    return _send(msg, category="heartbeat")


def daily_summary(summary: dict) -> bool:
    """Send end-of-day summary."""
    if not _enabled:
        return False
    msg = (
        f"📅 *Daily summary*\n"
        f"P&L: ₹{summary.get('daily_pnl', 0):,.0f}\n"
        f"Trades: {summary.get('trades_today', 0)}\n"
        f"Open: {summary.get('open_positions', 0)}\n"
        f"Capital: ₹{summary.get('capital', 0):,.0f}"
    )
    return _send(msg, category="daily", force=True)  # always send daily


def session_event(event: str, details: Optional[dict] = None) -> bool:
    """Session start/stop/restart notification."""
    if not _enabled:
        return False
    msg = f"🔄 *{event}*"
    if details:
        msg += "\n" + "\n".join(f"  {k}: {v}" for k, v in list(details.items())[:5])
    return _send(msg, category="session", force=True)


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--test-decision", action="store_true")
    p.add_argument("--test-risk", action="store_true")
    p.add_argument("--test-heartbeat", action="store_true")
    p.add_argument("--status", action="store_true")
    args = p.parse_args()

    a = get_alerter()
    if args.status or not any([args.test_decision, args.test_risk, args.test_heartbeat]):
        print(f"Alerter enabled: {_enabled}")
        print(f"Alerter object: {a}")
        sys.exit(0)

    if args.test_decision:
        ok = decision_made({"type": "OPEN", "underlying": "NIFTY", "strategy": "iron_condor",
                            "rationale": "Test alert from CLI", "target": 6000, "stop": 3000,
                            "max_hold_minutes": 240})
        print(f"decision_made: {ok}")

    if args.test_risk:
        ok = risk_alert("Test risk alert", severity="warning", details={"drawdown": "5%"})
        print(f"risk_alert: {ok}")

    if args.test_heartbeat:
        ok = heartbeat({"capital": 109978, "realized_pnl": 9978, "open_positions": 0, "tick": 4002})
        print(f"heartbeat: {ok}")
