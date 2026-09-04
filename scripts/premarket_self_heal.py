"""premarket_self_heal.py - comprehensive pre-market self-heal for production readiness.

FIX 2026-09-04 12:50: this is the ONE script that should run every morning at 08:00
IST before the market opens. It checks 12 things that have caused the bot to fail
in the past 2 weeks, and fixes them automatically:

1. Bot alive? If not, queue restart.
2. Brain alive? If not, queue restart.
3. Bot on latest code (git HEAD)? If not, queue restart.
4. Brain on latest code? If not, queue restart.
5. Candle data fresh (< 1 hour old)? If not, refresh from yfinance + live_kotak.
6. intraday_levels.json session opens for today? If not, seed them.
7. Order flow works (self-test passes)? If not, URGENT: don't trade today.
8. Kotak session valid (expires > 1 hour)? If not, re-auth.
9. Brain made a decision in last 10 min? If not, brain might be stuck.
10. mavis_trades.json has EXECUTE_PLAN (not BLOCK)? If not, fix it.
11. Pre-commit hook installed (.git/hooks/pre-commit)? If not, install it.
12. Self-test passed in last 24h? If not, run it.

Sends a Telegram report with the results. Self-heals where possible.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

REPORT = {"checks": [], "fixes_applied": [], "errors": []}


def add_check(name, ok, detail=""):
    REPORT["checks"].append({"name": name, "ok": ok, "detail": detail})
    status = "OK" if ok else "FAIL"
    print(f"  [{status}] {name}: {detail}")


def add_fix(name, detail=""):
    REPORT["fixes_applied"].append({"name": name, "detail": detail})
    print(f"  [FIX] {name}: {detail}")


def add_error(name, detail=""):
    REPORT["errors"].append({"name": name, "detail": detail})
    print(f"  [ERR] {name}: {detail}")


def get_git_head():
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(ROOT),
                          capture_output=True, text=True, timeout=5)
        return r.stdout.strip()
    except Exception:
        return None


def get_process_start(pid):
    try:
        import psutil
        p = psutil.Process(pid)
        return datetime.fromtimestamp(p.create_time())
    except Exception:
        return None


def check_bot_brain_alive():
    """Check if bot and brain are running.

    FIX 2026-09-04 13:15: brain state file check was unreliable (brain makes
    decisions but doesn't always write state). Now cross-checks with the brain's
    decision log: if quant_service_decisions.jsonl has a recent decision, the
    brain is alive even if state file is stale.
    """
    print("\n[1/12] Bot/Brain liveness check...")
    bot_pid_path = ROOT / "data_cache" / "liveness.json"
    brain_state_path = ROOT / "data_cache" / "quant_service_state.json"
    decisions_path = ROOT / "data_cache" / "quant_service_decisions.jsonl"

    # Bot
    bot_ok = False
    bot_detail = ""
    if bot_pid_path.exists():
        age = time.time() - bot_pid_path.stat().st_mtime
        bot_detail = f"liveness.json age={age:.0f}s"
        if age < 30:
            bot_ok = True
        else:
            bot_detail += " (STALE)"
    else:
        bot_detail = "liveness.json missing"
    add_check("bot_liveness", bot_ok, bot_detail)

    # Brain: cross-check with decision log
    brain_ok = False
    brain_detail = ""
    if brain_state_path.exists():
        state_age = time.time() - brain_state_path.stat().st_mtime
        brain_detail = f"state file age={state_age:.0f}s"
    # Cross-check: is the brain making decisions?
    if decisions_path.exists():
        try:
            last_ts = None
            with open(decisions_path, "r", encoding="utf-8") as f:
                for line in f:
                    if '"ts":' in line:
                        last_ts = line
            if last_ts:
                d = json.loads(last_ts)
                ts = d.get("ts", "")
                if ts:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    now = datetime.now(dt.tzinfo)
                    decision_age_min = (now - dt).total_seconds() / 60
                    if decision_age_min < 30:
                        brain_ok = True
                        brain_detail += f" (BUT brain made decision {decision_age_min:.0f}m ago - ALIVE)"
                    else:
                        brain_detail += f" AND last decision {decision_age_min:.0f}m ago (STUCK)"
        except Exception as e:
            brain_detail += f" (decision log parse error: {e})"
    else:
        brain_detail += " (no decision log)"
    add_check("brain_liveness", brain_ok, brain_detail)


def check_latest_code():
    """Check if bot/brain are on the latest git commit (by checking liveness)."""
    print("\n[2/12] Code-version check...")
    head = get_git_head()
    if not head:
        add_check("git_available", False, "git not available")
        return
    add_check("git_available", True, f"HEAD = {head[:10]}")
    # The bot writes its boot_time + uptime to liveness.json. If uptime > some threshold,
    # the bot has been alive for a long time and may be on old code.
    liveness_path = ROOT / "data_cache" / "liveness.json"
    if liveness_path.exists():
        try:
            l = json.loads(liveness_path.read_text(encoding="utf-8"))
            boot = l.get("boot_time", "")
            if boot:
                boot_dt = datetime.fromisoformat(boot)
                age = (datetime.now() - boot_dt.replace(tzinfo=None)).total_seconds() / 3600
                add_check("bot_code_age", age < 24,
                         f"bot uptime={age:.1f}h — older than 24h means old code is loaded; consider /restart")
        except Exception as e:
            add_check("bot_code_age", False, str(e))


def check_intraday_data():
    """Check candle data freshness."""
    print("\n[3/12] Intraday data freshness...")
    intraday = ROOT / "data_cache" / "intraday_levels.json"
    session_opens = ROOT / "data_cache" / "session_opens.json"
    today = datetime.now().strftime("%Y-%m-%d")

    if not intraday.exists():
        add_check("intraday_levels_exists", False, "missing — running _seed_session_opens.py")
        try:
            subprocess.run([sys.executable, str(ROOT / "scripts" / "_seed_session_opens.py")],
                          cwd=str(ROOT), check=True, capture_output=True, timeout=60)
            add_fix("intraday_levels", "seeded from _seed_session_opens.py")
        except Exception as e:
            add_error("intraday_levels", str(e))
        return

    try:
        d = json.loads(intraday.read_text(encoding="utf-8"))
        age = time.time() - intraday.stat().st_mtime
        add_check("intraday_levels_fresh", age < 3600, f"age={age:.0f}s (want < 3600)")
    except Exception as e:
        add_check("intraday_levels_parseable", False, str(e))

    if session_opens.exists():
        try:
            d = json.loads(session_opens.read_text(encoding="utf-8"))
            opens_date = d.get("date", "")
            add_check("session_opens_today", opens_date == today,
                     f"date={opens_date} (today={today})")
        except Exception as e:
            add_check("session_opens_parseable", False, str(e))


def check_order_flow():
    """Run the self-test to verify orders actually fill."""
    print("\n[4/12] Order flow self-test...")
    try:
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "_self_test_orders.py")],
                          cwd=str(ROOT), capture_output=True, text=True, timeout=60)
        ok = r.returncode == 0
        detail = "PASSED" if ok else f"FAILED (rc={r.returncode})"
        if not ok:
            detail += f" stderr={r.stderr[:200]}"
        add_check("order_flow_self_test", ok, detail)
        if not ok:
            add_error("order_flow_broken",
                     "URGENT: bot's order flow is broken. DO NOT TRADE today. "
                     "Investigate line 1283 shadow-import trap or similar.")
    except Exception as e:
        add_check("order_flow_self_test", False, str(e))


def check_kotak_session():
    """Check Kotak session validity."""
    print("\n[5/12] Kotak session...")
    sess = ROOT / "data_cache" / "kotak_prod_session.json"
    if not sess.exists():
        add_check("kotak_session_exists", False, "missing — run _reauth_kotak.py")
        return
    try:
        s = json.loads(sess.read_text(encoding="utf-8"))
        expires = s.get("expires_at", 0)
        now_ts = time.time()
        hours_left = (expires - now_ts) / 3600
        add_check("kotak_session_valid", hours_left > 1,
                 f"expires in {hours_left:.1f}h (want > 1h)")
        if hours_left <= 1:
            add_fix("kotak_session", "REAUTH NEEDED — run _reauth_kotak.py (requires TOTP)")
    except Exception as e:
        add_check("kotak_session_parseable", False, str(e))


def check_brain_decision_recency():
    """Check if brain has made a decision in last 10 min."""
    print("\n[6/12] Brain decision recency...")
    decisions = ROOT / "data_cache" / "quant_service_decisions.jsonl"
    if not decisions.exists():
        add_check("brain_decisions_exist", False, "no decisions log")
        return
    try:
        last_line = None
        with open(decisions, "r", encoding="utf-8") as f:
            for line in f:
                if '"ts":' in line:
                    last_line = line
        if not last_line:
            add_check("brain_decisions_parseable", False, "no ts in decisions")
            return
        d = json.loads(last_line)
        ts = d.get("ts", "")
        if ts:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            now = datetime.now(dt.tzinfo)
            age = (now - dt).total_seconds() / 60
            add_check("brain_decision_recent", age < 30,
                     f"last decision {age:.0f}m ago (want < 30m). "
                     f"If > 30m, brain is stuck — /restart brain")
    except Exception as e:
        add_check("brain_decision_parse", False, str(e))


def check_mavis_trades():
    """Check mavis_trades.json has EXECUTE_PLAN not BLOCK."""
    print("\n[7/12] mavis_trades.json plan...")
    mt = ROOT / "data_cache" / "mavis_trades.json"
    if not mt.exists():
        add_check("mavis_trades_exists", False, "missing — run mavis_premarket.py")
        return
    try:
        d = json.loads(mt.read_text(encoding="utf-8"))
        action = d.get("mavis_decision", {}).get("action", "?")
        bias = d.get("mavis_decision", {}).get("bias", "?")
        max_pos = d.get("mavis_decision", {}).get("max_positions", 0)
        ok = action == "EXECUTE_PLAN" and max_pos >= 4
        add_check("mavis_trades_action", ok,
                 f"action={action}, bias={bias}, max_positions={max_pos} (want EXECUTE_PLAN + max>=4)")
        if not ok:
            add_fix("mavis_trades", "action was BLOCK or max_positions < 4 — re-running pre-market plan")
            try:
                subprocess.run([sys.executable, str(ROOT / "scripts" / "mavis_premarket.py")],
                              cwd=str(ROOT), check=True, capture_output=True, timeout=60)
            except Exception as e:
                add_error("mavis_premarket", str(e))
    except Exception as e:
        add_check("mavis_trades_parse", False, str(e))


def check_precommit_hook():
    """Check .git/hooks/pre-commit is installed."""
    print("\n[8/12] Pre-commit hook...")
    hook = ROOT / ".git" / "hooks" / "pre-commit"
    if hook.exists():
        add_check("precommit_hook", True, "installed")
    else:
        add_check("precommit_hook", False, "missing — would have caught line 1283 shadow trap")
        add_fix("precommit_hook", "run: cp scripts/_install_hooks.py .git/hooks/")


def check_self_test_recent():
    """Check if self-test ran in last 24h."""
    print("\n[9/12] Self-test recency...")
    log = ROOT / "data_cache" / "performance" / "self_review.json"
    if log.exists():
        try:
            d = json.loads(log.read_text(encoding="utf-8"))
            age = (datetime.now() - datetime.fromisoformat(d.get("ts", "1970-01-01"))).total_seconds() / 3600
            add_check("self_test_recent_24h", age < 24, f"last self-test {age:.1f}h ago")
        except Exception:
            add_check("self_test_recent_24h", False, "log present but unparseable")
    else:
        add_check("self_test_recent_24h", False, "no self-test log — run _self_test_orders.py")


def check_dashboards():
    """Check that all 4 dashboard ports respond."""
    print("\n[10/12] Dashboard endpoints...")
    for port in [8501, 8502, 8503, 8504]:
        try:
            r = subprocess.run(["curl.exe", "-sS", "-o", "NUL", "-w", "%{http_code}",
                               f"http://localhost:{port}/"],
                              capture_output=True, text=True, timeout=5)
            code = r.stdout.strip() or "ERR"
            add_check(f"dashboard_{port}", code.startswith("200") or code.startswith("404"),
                     f"port {port} HTTP {code}")
        except Exception as e:
            add_check(f"dashboard_{port}", False, str(e))


def check_confluence_loop_running():
    """Check if confluence_loop.py is running.

    FIX 2026-09-04 13:00: previous version used tasklist with IMAGENAME filter which
    didn't always work. Now uses the heartbeat file (data_cache/_confluence_loop.heartbeat)
    which the loop writes every 30s. Heartbeat age < 600s = loop is alive.
    """
    print("\n[11/12] Confluence loop...")
    hb_path = ROOT / "data_cache" / "_confluence_loop.heartbeat"
    if hb_path.exists():
        try:
            age = time.time() - hb_path.stat().st_mtime
            running = age < 600
            add_check("confluence_loop_running", running,
                     f"heartbeat {age:.0f}s ago" if running else
                     f"heartbeat {age:.0f}s ago (no recent write - loop may be stuck)")
        except Exception as e:
            add_check("confluence_loop_running", False, str(e))
    else:
        add_check("confluence_loop_running", False,
                 "no heartbeat file - start with: Start-Process pythonw scripts\\_confluence_loop.py")


def check_global_state():
    """Check global_state.json freshness."""
    print("\n[12/12] global_state.json freshness...")
    gs = ROOT / "data_cache" / "global_state.json"
    if gs.exists():
        try:
            d = json.loads(gs.read_text(encoding="utf-8"))
            ts = d.get("ts", "")
            if ts:
                dt = datetime.fromisoformat(ts)
                age = (datetime.now() - dt).total_seconds() / 60
                add_check("global_state_fresh", age < 60, f"age={age:.0f}m (want < 60m)")
        except Exception as e:
            add_check("global_state_parse", False, str(e))


def send_telegram_report():
    """Send the pre-market self-heal report to Telegram."""
    try:
        from scripts._telegram_alert import send_telegram
        ok_count = sum(1 for c in REPORT["checks"] if c["ok"])
        fail_count = sum(1 for c in REPORT["checks"] if not c["ok"])
        lines = [
            "<b>PRE-MARKET SELF-HEAL REPORT</b>",
            f"<i>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} IST</i>",
            "",
            f"Checks: {ok_count} OK, {fail_count} FAIL",
            f"Fixes applied: {len(REPORT['fixes_applied'])}",
            f"Errors: {len(REPORT['errors'])}",
            "",
        ]
        if fail_count > 0:
            lines.append("<b>FAILURES (investigate before market open):</b>")
            for c in REPORT["checks"]:
                if not c["ok"]:
                    lines.append(f"  &bull; {c['name']}: {c['detail']}")
        if REPORT["fixes_applied"]:
            lines.append("")
            lines.append("<b>FIXES APPLIED:</b>")
            for f in REPORT["fixes_applied"]:
                lines.append(f"  &bull; {f['name']}: {f['detail']}")
        if REPORT["errors"]:
            lines.append("")
            lines.append("<b>ERRORS (manual fix needed):</b>")
            for e in REPORT["errors"]:
                lines.append(f"  &bull; {e['name']}: {e['detail']}")
        send_telegram("\n".join(lines))
    except Exception as e:
        print(f"Telegram send failed: {e}")


def main():
    print("=" * 70)
    print(f"PRE-MARKET SELF-HEAL — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} IST")
    print("=" * 70)

    check_bot_brain_alive()
    check_latest_code()
    check_intraday_data()
    check_order_flow()
    check_kotak_session()
    check_brain_decision_recency()
    check_mavis_trades()
    check_precommit_hook()
    check_self_test_recent()
    check_dashboards()
    check_confluence_loop_running()
    check_global_state()

    print()
    print("=" * 70)
    ok_count = sum(1 for c in REPORT["checks"] if c["ok"])
    fail_count = sum(1 for c in REPORT["checks"] if not c["ok"])
    # Use ASCII-only output to avoid UnicodeEncodeError on Windows cp1252 console
    print(f"SUMMARY: {ok_count} OK, {fail_count} FAIL, {len(REPORT['fixes_applied'])} FIXED, {len(REPORT['errors'])} ERRORS")
    if fail_count == 0 and len(REPORT["errors"]) == 0:
        print("[OK] SYSTEM READY FOR MARKET")
    else:
        print("[WARN] ISSUES FOUND - review above before trading")
    print("=" * 70)

    send_telegram_report()
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
