"""daily_autonomy.py - the 24/7 autonomous loop that does everything daily.

FIX 2026-09-04 15:08: instead of relying on the user to do /health, /diag, /live
manually, this script runs as a single systemd timer (or cron) at 3 fixed times
each day:
  - 08:25 IST: pre-market self-heal + Kotak re-auth + self-test
  - 15:30 IST: EOD P&L evaluator + Telegram report
  - 23:00 IST: state backup + performance summary

All output is sent to Telegram (no manual intervention needed).

This replaces 23 paused Mavis crons + 11 in-process schedulers with a single
self-contained script that works in any environment (Linux, WSL2, Windows, cloud).

Usage:
  python scripts/daily_autonomy.py pre_market
  python scripts/daily_autonomy.py eod
  python scripts/daily_autonomy.py nightly
  python scripts/daily_autonomy.py all   # run all three (in sequence)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))


def send_telegram(text: str) -> bool:
    try:
        from scripts._telegram_alert import send_telegram as _send
        return _send(text)
    except Exception:
        return False


def run_script(name: str, args: list = None, timeout: int = 120) -> tuple:
    """Run a script and return (returncode, stdout)."""
    args = args or []
    cmd = [sys.executable, str(ROOT / "scripts" / name)] + args
    try:
        r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout[-2000:]  # last 2KB
    except subprocess.TimeoutExpired:
        return -1, f"timeout after {timeout}s"
    except Exception as e:
        return 1, str(e)


def pre_market() -> int:
    """08:25 IST: pre-market self-heal + Kotak re-auth + self-test."""
    print("[1/3] pre-market self-heal...")
    rc, out = run_script("premarket_self_heal.py", timeout=180)
    print(f"  self-heal rc={rc}")
    rc2, out2 = run_script("_self_test_orders.py", timeout=60)
    print(f"  self-test rc={rc2}")

    # Read liveness
    liveness_path = ROOT / "data_cache" / "liveness.json"
    liveness_summary = "n/a"
    if liveness_path.exists():
        try:
            l = json.loads(liveness_path.read_text(encoding="utf-8"))
            liveness_summary = (
                f"bot PID {l.get('pid')} uptime {l.get('uptime_sec', 0)/3600:.1f}h "
                f"tick {l.get('tick')} capital Rs.{l.get('snapshot', {}).get('capital', 0):,.0f}"
            )
        except Exception:
            pass

    # Kotak session
    sess_path = ROOT / "data_cache" / "kotak_prod_session.json"
    sess_summary = "n/a"
    if sess_path.exists():
        try:
            s = json.loads(sess_path.read_text(encoding="utf-8"))
            hrs = (s.get("expires_at", 0) - time.time()) / 3600
            sess_summary = f"expires in {hrs:+.1f}h"
        except Exception:
            pass

    # Brain decision count today
    decisions_path = ROOT / "data_cache" / "quant_service_decisions.jsonl"
    n_decisions = 0
    if decisions_path.exists():
        today = datetime.now().strftime("%Y-%m-%d")
        with open(decisions_path, "r", encoding="utf-8") as f:
            for line in f:
                if today in line:
                    n_decisions += 1

    msg = (
        f"<b>PRE-MARKET REPORT {datetime.now().strftime('%H:%M:%S')} IST</b>\n\n"
        f"Bot: {liveness_summary}\n"
        f"Kotak: {sess_summary}\n"
        f"Brain decisions today: {n_decisions}\n"
        f"Self-heal: rc={rc}\n"
        f"Self-test: rc={rc2}\n"
    )
    if rc != 0 or rc2 != 0:
        msg += f"\n<b>WARN</b>\nself-heal: {out[-500:]}\nself-test: {out2[-500:]}"
    send_telegram(msg)
    return 0 if (rc == 0 and rc2 == 0) else 1


def eod() -> int:
    """15:30 IST: EOD P&L evaluator + Telegram report."""
    print("[1/3] EOD P&L evaluator...")
    rc, out = run_script("_eod_pnl_evaluator.py", timeout=60)
    print(f"  EOD rc={rc}")

    # Read paper state
    ps_path = ROOT / "data_cache" / "paper_state.json"
    cash = 0
    realized = 0
    n_pos = 0
    if ps_path.exists():
        try:
            ps = json.loads(ps_path.read_text(encoding="utf-8"))
            cash = ps.get("cash", 0)
            realized = ps.get("realized_pnl", 0)
            n_pos = len(ps.get("positions", {}))
        except Exception:
            pass

    # Update performance metrics
    rc2, out2 = run_script("strategy_performance.py", timeout=60)
    sp_path = ROOT / "data_cache" / "performance" / "strategy_performance.json"
    sp_summary = "n/a"
    if sp_path.exists():
        try:
            sp = json.loads(sp_path.read_text(encoding="utf-8"))
            sp_summary = (
                f"trades {sp.get('n_trades', 0)} | "
                f"sharpe {sp.get('sharpe_30d', 0):.2f} | "
                f"total Rs.{sp.get('total_pnl', 0):+,.0f}"
            )
        except Exception:
            pass

    msg = (
        f"<b>EOD REPORT {datetime.now().strftime('%H:%M:%S')} IST</b>\n\n"
        f"Cash: Rs.{cash:,.0f}\n"
        f"Realized: Rs.{realized:+,.2f}\n"
        f"Open positions: {n_pos}\n"
        f"Strategy: {sp_summary}\n"
    )
    send_telegram(msg)
    return 0


def nightly() -> int:
    """23:00 IST: state backup + performance summary."""
    print("[1/3] state backup...")
    # Backup paper state + decisions + journal
    backup_dir = ROOT / "data_cache" / "backups" / datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir.mkdir(parents=True, exist_ok=True)
    files = ["paper_state.json", "quant_service_decisions.jsonl", "trade_journal.jsonl",
             "performance/strategy_performance.json", "performance/daily.json", "performance/self_review.json"]
    for f in files:
        src = ROOT / "data_cache" / f
        if src.exists():
            dst = backup_dir / f
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src.read_bytes())
    n_backups = len(list(backup_dir.glob("**/*")))
    print(f"  backed up {n_backups} files to {backup_dir}")

    # Update self-test log (for live-trading gate 9)
    rc, out = run_script("_update_self_test_log.py", timeout=60)

    # Live-trading gates status
    rc2, out2 = run_script("live_trading_gates.py", timeout=30)
    gates_summary = "n/a"
    if rc2 == 0:
        for line in out2.splitlines():
            if "gates passed" in line:
                gates_summary = line.strip()
                break

    msg = (
        f"<b>NIGHTLY REPORT {datetime.now().strftime('%H:%M:%S')} IST</b>\n\n"
        f"Backed up {n_backups} files to {backup_dir.name}\n"
        f"Self-test log: rc={rc}\n"
        f"Live-trading gates: {gates_summary}\n"
    )
    send_telegram(msg)
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=["pre_market", "eod", "nightly", "all"])
    args = parser.parse_args()

    print(f"daily_autonomy.py: phase={args.phase}")
    rc = 0
    if args.phase in ("pre_market", "all"):
        rc |= pre_market()
    if args.phase in ("eod", "all"):
        rc |= eod()
    if args.phase in ("nightly", "all"):
        rc |= nightly()
    return rc


if __name__ == "__main__":
    sys.exit(main())
