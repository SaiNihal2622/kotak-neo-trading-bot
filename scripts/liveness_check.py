"""Liveness watchdog — checks if the bot is alive and reports a JSON status.

Used by external cron jobs (kotak-bot-247-watchdog) to detect dead bots
and emit Telegram alerts when liveness goes stale.

Usage:
    python scripts/liveness_check.py
    python scripts/liveness_check.py --max-age 60
    python scripts/liveness_check.py --json
    python scripts/liveness_check.py --telegram  # send alert if stale

Exit codes:
    0  Bot is alive (liveness file fresh)
    1  Bot is DEAD (liveness file missing or stale)
    2  Bot is alive but in a warning state (paused / errors in provider)
    3  Error running the check itself
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Force UTF-8 stdout on Windows (cp1252 can't encode emoji)
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def _now() -> datetime:
    return datetime.now().astimezone()


def _parse_iso(ts: str) -> datetime:
    # Python 3.11+ fromisoformat handles offset suffixes; older needs replace
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        # Try with manual parsing for older Python
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def check_liveness(
    ping_file: str = "data_cache/liveness.json",
    max_age_sec: float = 90.0,
) -> dict:
    """Return a status dict describing the bot's liveness."""
    result = {
        "checked_at": _now().isoformat(),
        "ping_file": ping_file,
        "alive": False,
        "age_sec": None,
        "max_age_sec": max_age_sec,
        "reason": None,
        "snapshot": None,
        "uptime_sec": None,
        "pid": None,
    }
    p = Path(ping_file)
    if not p.exists():
        result["reason"] = "liveness_file_missing"
        return result
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        result["reason"] = f"liveness_file_corrupt: {e}"
        return result
    except Exception as e:
        result["reason"] = f"liveness_file_read_error: {e}"
        return result

    ts_str = data.get("ts")
    if not ts_str:
        result["reason"] = "liveness_file_no_ts"
        return result
    try:
        ts = _parse_iso(ts_str)
    except Exception as e:
        result["reason"] = f"liveness_ts_parse_error: {e}"
        return result
    age = (_now() - ts).total_seconds()
    result["age_sec"] = round(age, 1)
    result["uptime_sec"] = data.get("uptime_sec")
    result["pid"] = data.get("pid")
    result["snapshot"] = data.get("snapshot", {})
    if age <= max_age_sec:
        result["alive"] = True
        result["reason"] = "fresh"
    else:
        result["reason"] = f"stale_{int(age)}s"
    return result


def format_telegram(result: dict) -> str:
    """Render a human-readable status line for Telegram."""
    if result["alive"]:
        snap = result.get("snapshot") or {}
        cap = snap.get("capital")
        pnl = snap.get("realized_pnl")
        pos = snap.get("open_positions")
        vix = snap.get("vix")
        msg = f"✅ Bot ALIVE (age={result['age_sec']}s, pid={result['pid']}, uptime={result['uptime_sec']}s)"
        if cap is not None:
            msg += f"\n💰 Capital: ₹{cap:,.0f} | Realized: ₹{pnl:,.0f}" if pnl is not None else f"\n💰 Capital: ₹{cap:,.0f}"
        if pos is not None:
            msg += f" | Open positions: {pos}"
        if vix is not None:
            msg += f" | VIX: {vix:.2f}"
        return msg
    return f"❌ Bot DEAD: {result['reason']} (file={result['ping_file']})"


def main() -> int:
    p = argparse.ArgumentParser(description="Liveness watchdog for the kotak bot")
    p.add_argument("--ping-file", default="data_cache/liveness.json",
                   help="Path to the liveness ping file (default: data_cache/liveness.json)")
    p.add_argument("--max-age", type=float, default=90.0,
                   help="Max acceptable age of liveness file in seconds (default: 90)")
    p.add_argument("--json", action="store_true", help="Emit JSON only")
    p.add_argument("--telegram", action="store_true",
                   help="Send a Telegram message if state changed since last run")
    p.add_argument("--state-file", default="data_cache/liveness_watchdog_state.json",
                   help="File used to track last reported state (for --telegram)")
    args = p.parse_args()

    try:
        result = check_liveness(args.ping_file, args.max_age)
    except Exception as e:
        if args.json:
            print(json.dumps({"error": str(e), "type": type(e).__name__}))
        else:
            print(f"ERROR: check failed: {e}", file=sys.stderr)
        return 3

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(format_telegram(result))

    # Optional: send Telegram if state changed
    if args.telegram:
        state_path = Path(args.state_file)
        prev_state = None
        if state_path.exists():
            try:
                prev_state = json.loads(state_path.read_text(encoding="utf-8"))
            except Exception:
                prev_state = None
        curr_state = "alive" if result["alive"] else "dead"
        if prev_state is None or prev_state.get("state") != curr_state:
            try:
                import os
                from kotak_bot.alerts.telegram import TelegramAlerter
                alerter = TelegramAlerter(voice_enabled=False)
                msg = format_telegram(result)
                if not result["alive"]:
                    msg = f"🚨 ALERT: {msg}"
                alerter.send(msg)
                state_path.parent.mkdir(parents=True, exist_ok=True)
                state_path.write_text(
                    json.dumps({"state": curr_state, "ts": _now().isoformat()}, indent=2),
                    encoding="utf-8",
                )
                if not args.json:
                    print(f"\n[TELEGRAM] sent alert (state: {curr_state})")
            except Exception as e:
                if not args.json:
                    print(f"\n[TELEGRAM] send failed: {e}", file=sys.stderr)
        else:
            if not args.json:
                print(f"\n[TELEGRAM] state unchanged ({curr_state}), skipping")

    return 0 if result["alive"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
