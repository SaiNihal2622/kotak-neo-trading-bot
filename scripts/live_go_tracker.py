"""FIX 2026-09-17 13:55: live-go policy tracker.

Evaluates whether the bot is ready to switch from paper to live trading
based on the user's policy: "we do live after we see profits in paper
trades for some days" (2026-09-17 13:51 IST).

Three conditions must hold simultaneously for the gate to flip READY:
  1. >= N consecutive paper-trading days with positive net P&L (default 5)
  2. Cumulative paper return > +X% from baseline (default 5%)
  3. All non-env live-trading gates passing (default true)

The user can edit data_cache/live_go_policy.json to override defaults.

Writes:
  - data_cache/live_go_status.json — current progress for the dashboard
  - Sends Telegram alert when ALL conditions flip to met

Run: python scripts/live_go_tracker.py [--check-only]
Schedule: daily at 15:30 IST (after market close) via _scheduled_subprocess
in scripts/quant_service.py.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
DCACHE = ROOT / "data_cache"
sys.path.insert(0, str(ROOT))


def _load_policy() -> dict:
    """FIX 2026-09-17 13:55: load go-live policy from JSON file.
    Creates default policy if missing. User can edit to override.
    """
    p = DCACHE / "live_go_policy.json"
    if not p.exists():
        # First run — create default policy
        p.parent.mkdir(parents=True, exist_ok=True)
        default = {
            "_comment": "FIX 2026-09-17 13:55: go-live policy.",
            "min_consecutive_green_days": 5,
            "min_cumulative_return_pct": 5.0,
            "require_all_gates_passing": True,
            "reset_on_any_losing_day": True,
            "starting_capital_baseline": 100000,
            "telegram_alert_on_ready": True,
            "daily_check_time_ist": "15:30",
        }
        p.write_text(json.dumps(default, indent=2), encoding="utf-8")
        return default
    return json.loads(p.read_text(encoding="utf-8"))


def _daily_pnl_from_strategy_perf() -> dict[str, float]:
    """Read daily P&L from strategy_performance.json's by_day section.
    Returns {YYYY-MM-DD: pnl}. Includes ALL days regardless of mode.
    """
    sp = DCACHE / "performance" / "strategy_performance.json"
    if not sp.exists():
        return {}
    try:
        d = json.loads(sp.read_text(encoding="utf-8"))
        out = {}
        for date, rec in (d.get("by_day") or {}).items():
            try:
                out[date] = float(rec.get("pnl", 0) or 0)
            except Exception:
                continue
        return out
    except Exception:
        return {}


def _consecutive_green_days(daily_pnl: dict[str, float]) -> tuple[int, str]:
    """FIX 2026-09-17 13:55: count the current streak of consecutive
    profitable days. Returns (streak_count, last_green_day_str) where
    last_green_day is the most recent (last) green day in the streak.
    """
    if not daily_pnl:
        return 0, ""
    sorted_days = sorted(daily_pnl.keys())
    streak = 0
    # Iterate from newest to oldest, count green until we hit a red day.
    # Track the LAST day we counted (most recent green day) — this is the
    # day the streak ENDS, not the day it starts.
    for day in reversed(sorted_days):
        if daily_pnl.get(day, 0) > 0:
            streak += 1
        else:
            break
    # The "last day" is the MOST RECENT day in the streak (where the streak
    # ends). This is the most recent day the bot made money.
    last_green_day = ""
    if streak > 0 and sorted_days:
        last_green_day = sorted_days[-1]
    return streak, last_green_day


def _cumulative_return_pct(daily_pnl: dict[str, float], baseline: float) -> tuple[float, float]:
    """FIX 2026-09-17 13:55: compute total cumulative P&L and return %.
    Returns (cumulative_pnl_rs, return_pct).
    """
    if not daily_pnl or baseline <= 0:
        return 0.0, 0.0
    total = sum(daily_pnl.values())
    return total, total / baseline * 100


def _all_gates_passing() -> tuple[bool, str]:
    """FIX 2026-09-17 13:55: check live-trading gates (excludes env).
    Returns (live_readiness_pct=100, status_msg).
    """
    try:
        from scripts.live_trading_gates import run_all_gates
        report = run_all_gates()
        pct = report.get("live_readiness_pct", 0)
        return pct >= 100.0, f"live-readiness {pct:.1f}%"
    except Exception as e:
        return False, f"gate check failed: {e}"


def main() -> int:
    policy = _load_policy()
    daily_pnl = _daily_pnl_from_strategy_perf()
    streak, last_day = _consecutive_green_days(daily_pnl)
    cumulative_pnl, cumulative_pct = _cumulative_return_pct(
        daily_pnl, policy.get("starting_capital_baseline", 100000)
    )
    gates_ok, gates_msg = _all_gates_passing()

    min_streak = int(policy.get("min_consecutive_green_days", 5))
    min_return = float(policy.get("min_cumulative_return_pct", 5.0))
    require_gates = bool(policy.get("require_all_gates_passing", True))

    cond_streak_ok = streak >= min_streak
    cond_return_ok = cumulative_pct >= min_return
    cond_gates_ok = (gates_ok if require_gates else True)

    all_ok = cond_streak_ok and cond_return_ok and cond_gates_ok

    status = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "policy": {
            "min_consecutive_green_days": min_streak,
            "min_cumulative_return_pct": min_return,
            "require_all_gates_passing": require_gates,
        },
        "current": {
            "consecutive_green_days": streak,
            "last_green_day": last_day,
            "cumulative_pnl_rs": round(cumulative_pnl, 2),
            "cumulative_return_pct": round(cumulative_pct, 2),
            "n_days_evaluated": len(daily_pnl),
            "gates_status": gates_msg,
        },
        "conditions": {
            "consecutive_green_days": {
                "current": streak,
                "required": min_streak,
                "met": cond_streak_ok,
            },
            "cumulative_return": {
                "current_pct": round(cumulative_pct, 2),
                "required_pct": min_return,
                "met": cond_return_ok,
            },
            "all_gates_passing": {
                "status": gates_msg,
                "met": cond_gates_ok,
            },
        },
        "ready_for_live": all_ok,
        "missing_to_ready": [
            ("consecutive_green_days"
             if not cond_streak_ok
             else None),
            ("cumulative_return"
             if not cond_return_ok
             else None),
            ("all_gates_passing"
             if not cond_gates_ok
             else None),
        ],
    }
    # Drop Nones
    status["missing_to_ready"] = [m for m in status["missing_to_ready"] if m]
    if not status["missing_to_ready"]:
        status["missing_to_ready"] = []

    out_path = DCACHE / "live_go_status.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(status, indent=2), encoding="utf-8")

    # Print summary
    print(f"LIVE-GO POLICY: {'READY' if all_ok else 'NOT READY'}")
    print(f"  Consecutive green days: {streak}/{min_streak} {'OK' if cond_streak_ok else 'FAIL'}")
    if last_day:
        print(f"    (last green day: {last_day})")
    print(f"  Cumulative return: {cumulative_pct:+.2f}% / +{min_return}% "
          f"({'OK' if cond_return_ok else 'FAIL'})")
    print(f"  Cumulative P&L: Rs.{cumulative_pnl:+,.2f}")
    print(f"  Live-trading gates: {gates_msg} {'OK' if cond_gates_ok else 'FAIL'}")
    print(f"  Days evaluated: {len(daily_pnl)}")
    if all_ok:
        print()
        print("  ALL CONDITIONS MET — bot is ready for live trading.")
        print("  To enable live mode:")
        print("    $env:KOTAK_LIVE_CONFIRMED = 'YES'")
        print("    $env:KOTAK_ENV = 'prod'")
        print("    nssm restart KotakBotPaper")
    else:
        if status["missing_to_ready"]:
            print(f"  Missing: {', '.join(status['missing_to_ready'])}")

    # Telegram alert on ready (only fires once — when transitioning from not-ready to ready)
    if all_ok and policy.get("telegram_alert_on_ready", True):
        _send_telegram_alert_if_first_time(status)

    return 0


def _send_telegram_alert_if_first_time(status: dict) -> None:
    """FIX 2026-09-17 13:55: send Telegram alert on the first time the
    go-live policy flips to READY. Subsequent runs won't re-alert.
    State stored in data_cache/.live_go_alerted (dotfile to keep it
    from showing in normal listings).
    """
    flag = DCACHE / ".live_go_alerted"
    if flag.exists():
        return
    try:
        # Try to import the telegram alerter from the bot
        from kotak_bot.alerts.telegram import TelegramAlerter
        msg = (
            "[Live-Go READY] All conditions met for switching to live trading:\n\n"
            f"Consecutive green days: {status['conditions']['consecutive_green_days']['current']} "
            f"(need {status['policy']['min_consecutive_green_days']})\n"
            f"Cumulative return: {status['conditions']['cumulative_return']['current_pct']:+.2f}% "
            f"(need +{status['policy']['min_cumulative_return_pct']}%)\n"
            f"Live-trading gates: {status['conditions']['all_gates_passing']['status']}\n\n"
            "To enable live mode:\n"
            "  $env:KOTAK_LIVE_CONFIRMED = 'YES'\n"
            "  $env:KOTAK_ENV = 'prod'\n"
            "  nssm restart KotakBotPaper"
        )
        alerter = TelegramAlerter(voice_enabled=False)
        alerter.send(msg)
        flag.write_text(datetime.now(timezone.utc).isoformat())
    except Exception as e:
        # Best-effort; don't break the tracker on alerter failures
        print(f"  (telegram alert skipped: {e})")


if __name__ == "__main__":
    sys.exit(main())