"""Daily maintenance for the Kotak Neo bot.

Designed to be run by cron at 8:25 AM IST (5 min before market open). It
performs every unattended operation so the user doesn't have to touch
the system. Reports a single status to Telegram.

What it does (in order):
  1. Run self_test (yfinance, telegram, llm, kotak creds, paper state, dashboard, etc.)
  2. Re-authenticate with Kotak Neo (TOTP + MPIN) so the session is fresh
  3. Auto-rebuild positions if reconciliation shows orphans
  4. Re-verify power plan is High Performance
  5. Send a single "good morning" Telegram with the health summary

Usage:
    python scripts/daily_maintenance.py           # full flow + telegram
    python scripts/daily_maintenance.py --quiet   # no telegram (for testing)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / "config" / "credentials.env")

import httpx

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def send_telegram(text: str, silent: bool = False) -> bool:
    if silent or not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    try:
        # Try Markdown first; if it fails, retry as plain text
        r = httpx.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown",
                  "disable_web_page_preview": True},
            timeout=10,
        )
        j = r.json()
        if j.get("ok"):
            return True
        # fall back to plain text
        r2 = httpx.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "disable_web_page_preview": True},
            timeout=10,
        )
        return r2.json().get("ok", False)
    except Exception as e:
        print(f"telegram send failed: {e}")
        return False


def _powercfg_active() -> tuple[bool, str]:
    """Return (ok, name) for the current Windows power plan."""
    try:
        out = subprocess.run(
            ["powercfg", "/getactivescheme"],
            capture_output=True, text=True, timeout=10,
        )
        text = out.stdout
        if "High performance" in text:
            return True, "High performance"
        if "Balanced" in text:
            return False, "Balanced (will switch to High Performance)"
        return False, f"unknown: {text.strip()[:80]}"
    except Exception as e:
        return False, f"powercfg failed: {e}"


def _ensure_high_performance() -> tuple[bool, str]:
    """Switch to High performance if not already."""
    try:
        out = subprocess.run(
            ["powercfg", "/setactive", "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"],
            capture_output=True, text=True, timeout=10,
        )
        return out.returncode == 0, (out.stdout or out.stderr).strip() or "set"
    except Exception as e:
        return False, str(e)


def _disable_sleep_timeout() -> tuple[bool, str]:
    """Set 'sleep after' to 0 (never) on AC power."""
    try:
        out = subprocess.run(
            ["powercfg", "-change", "-standby-timeout-ac", "0"],
            capture_output=True, text=True, timeout=10,
        )
        return out.returncode == 0, (out.stdout or out.stderr).strip() or "set"
    except Exception as e:
        return False, str(e)


def _reauth_kotak() -> tuple[bool, str]:
    """Re-authenticate with Kotak Neo. Reads creds from env (already loaded above)."""
    try:
        from kotak_bot.broker.neo_client import NeoClient
        nc = NeoClient()
        nc.connect()
        if nc._client is not None and nc._connected:
            return True, f"auth OK, env={os.environ.get('KOTAK_ENV')}"
        return False, "connect returned but not in connected state"
    except Exception as e:
        return False, f"auth error: {e}"


def _reconcile_self_heal() -> tuple[bool, str]:
    """Check positions for orphans WITHOUT auto-rebuilding.

    Rebuilding from the order book is dangerous because the historical order
    book contains SELLs that were never recorded as positions (the original
    SELL bug). Rebuilding would resurrect them as ghost positions. Instead
    we just report the current state and let the user decide.
    """
    try:
        from kotak_bot.broker.paper_client import PaperClient
        pc = PaperClient(
            starting_capital=100_000.0,
            persist_path=str(ROOT / "data_cache" / "paper_state.json"),
        )
        pc.connect()
        positions = pc.get_positions()
        if not positions:
            return True, "no open positions (clean slate)"
        # report what's open
        syms = ", ".join(f"{p.symbol}({p.qty:+d})" for p in positions)
        return True, f"{len(positions)} open positions: {syms}"
    except Exception as e:
        return False, f"reconcile check failed: {e}"


def _run_self_test() -> dict:
    """Run the self-test module and return its report."""
    try:
        from scripts import self_test  # noqa: F401
    except Exception:
        sys.path.insert(0, str(ROOT))
        from scripts import self_test  # type: ignore
    return self_test.run_all()


def _run_smoke_test() -> dict:
    """Run the pre-market smoke test (read-only, exits with code 0/1/2)."""
    try:
        from scripts import pre_market_smoke_test  # noqa: F401
    except Exception:
        sys.path.insert(0, str(ROOT))
        from scripts import pre_market_smoke_test  # type: ignore
    result = pre_market_smoke_test.run_checks()
    return result


def main() -> int:
    quiet = "--quiet" in sys.argv
    print("=" * 60)
    print("Kotak Neo Bot — DAILY MAINTENANCE")
    print("Started:", datetime.utcnow().isoformat() + "Z")
    print("=" * 60)

    lines: list[str] = []
    critical_failures: list[str] = []

    # 1) Power plan
    ok, msg = _powercfg_active()
    print(f"  [{('OK' if ok else 'FIX')}] power plan: {msg}")
    if not ok:
        ok2, m2 = _ensure_high_performance()
        print(f"    -> {'set' if ok2 else 'failed'}: {m2}")
        if ok2:
            lines.append("✅ Power plan: switched to High performance")
        else:
            lines.append(f"⚠️ Power plan: {m2}")
            critical_failures.append("power plan")
    else:
        lines.append(f"✅ Power plan: {msg}")

    # 2) Sleep timeout
    ok, msg = _disable_sleep_timeout()
    print(f"  [{('OK' if ok else 'WARN')}] sleep timeout: {msg}")
    lines.append("✅ Sleep: never sleep on AC" if ok else f"⚠️ Sleep: {msg}")

    # 3) Self test
    print("\n  [..] running self-test (8 checks)...")
    report = _run_self_test()
    for r in report["results"]:
        mark = "OK" if r["ok"] else "FAIL"
        print(f"    [{mark}] {r['name']:14s}  {r['detail']}")
    failed = [r for r in report["results"] if not r["ok"]]
    if not failed:
        lines.append(f"✅ Self-test: {report['passed']}/{report['total']} checks passed")
    else:
        lines.append(f"⚠️ Self-test: {len(failed)} failure(s)")
        for r in failed:
            lines.append(f"   • `{r['name']}`: {r['detail']}")
            if r["name"] in ("yfinance", "telegram", "kotak_creds", "dashboard", "bot_process"):
                critical_failures.append(r["name"])

    # 3.5) Pre-market smoke test (production-level readiness gate)
    print("\n  [..] running pre-market smoke test (11 checks)...")
    smoke = _run_smoke_test()
    summary = smoke["summary"]
    print(f"    [SMOKE] status={summary['status']} critical_failures={summary['critical_failures']} warnings={summary['warnings']}")
    if summary["critical_failures"]:
        lines.append(f"🚫 Smoke test FAILED ({len(summary['critical_failures'])} critical)")
        for name in summary["critical_failures"]:
            r = smoke["results"].get(name, {})
            lines.append(f"   • `{name}`: {r.get('reason', 'see logs')}")
            critical_failures.append(f"smoke.{name}")
    elif summary["warnings"]:
        lines.append(f"⚠️ Smoke test: {len(summary['warnings'])} warning(s)")
        for name in summary["warnings"]:
            r = smoke["results"].get(name, {})
            lines.append(f"   • `{name}`: {r.get('reason', 'see logs')}")
    else:
        lines.append("✅ Smoke test: all 11 checks pass")

    # 4) Kotak re-auth (only if creds OK)
    if not [r for r in report["results"] if r["name"] == "kotak_creds" and not r["ok"]]:
        print("\n  [..] re-authenticating with Kotak Neo...")
        ok, msg = _reauth_kotak()
        print(f"  [{('OK' if ok else 'FAIL')}] kotak auth: {msg}")
        if ok:
            lines.append("✅ Kotak auth: fresh session")
        else:
            lines.append(f"⚠️ Kotak auth: {msg}")
            critical_failures.append("kotak auth")

    # 5) Reconcile self-heal
    print("\n  [..] reconciliation self-heal...")
    ok, msg = _reconcile_self_heal()
    print(f"  [{('OK' if ok else 'WARN')}] reconcile: {msg}")
    lines.append(f"✅ Reconcile: {msg}" if ok else f"⚠️ Reconcile: {msg}")

    # 6) Compose + send Telegram (no emojis on Windows console to avoid cp1252 issues)
    header = "**Good morning — daily maintenance complete**\n"
    if critical_failures:
        header = f"**[{len(critical_failures)} CRITICAL] — daily maintenance**\n"
    msg = header + "\n".join(lines)

    # for the console print, strip emojis
    safe_msg = msg.encode("ascii", "replace").decode("ascii")
    print("\n" + "=" * 60)
    print("TELEGRAM MESSAGE (sanitized for console):")
    print(safe_msg)
    print("=" * 60)
    sent = send_telegram(msg, silent=quiet)
    print(f"\nTelegram sent: {sent}")

    return 0 if not critical_failures else 1


if __name__ == "__main__":
    sys.exit(main())
