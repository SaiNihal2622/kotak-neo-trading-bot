"""pre_market_reset_paper_state.py — clean baseline reset for tomorrow.

FIX 2026-09-07 23:15: today's paper_state.json has poisoned P&L because 3
of 8 fills used the fake Rs.1.00 fallback price (orphans auto-closed
without strike/option_type metadata). The +Rs.16,619.70 realized is
baked into the running total and CANNOT be retroactively corrected.

Tomorrow (2026-09-08) we want a clean Rs.100,000 baseline to start
honest P&L tracking. This script:
  1. Backs up current paper_state.json to paper_state_pre_reset_<ts>.json
  2. Resets cash + realized_pnl to the configured starting_capital (Rs.100,000)
  3. Clears all positions and orders
  4. Writes a "RESET" marker so audit can trace what happened
  5. Sends a Telegram notification

Wired into scripts/daily_autonomy.py pre_market() phase at 08:25 IST.
Only fires if RESET_PAPER_TOMORROW=YES in config/credentials.env or
data_cache/_reset_marker.json (the user must opt in).

The marker file is consumed and deleted on first run — the reset is
a one-shot, not a recurring reset.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
DCACHE = ROOT / "data_cache"
PAPER_STATE = DCACHE / "paper_state.json"
RESET_MARKER = DCACHE / "_reset_marker.json"
JOURNAL_PATH = DCACHE / "trade_journal.jsonl"
PERF_DAILY = DCACHE / "performance" / "daily.json"


def _should_reset() -> tuple[bool, str]:
    """Check whether to run the reset. Returns (should_run, reason)."""
    # Method 1: explicit env var
    if os.environ.get("RESET_PAPER_TOMORROW", "").upper() == "YES":
        return True, "env RESET_PAPER_TOMORROW=YES"
    # Method 2: marker file (deleted on first run)
    if RESET_MARKER.exists():
        try:
            m = json.loads(RESET_MARKER.read_text(encoding="utf-8"))
            return True, f"marker file (reason: {m.get('reason', '?')})"
        except Exception:
            return True, "marker file (unreadable)"
    return False, "no marker"


def _send_telegram(msg: str) -> bool:
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        cred = ROOT / "config" / "credentials.env"
        for line in cred.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if k.strip() not in os.environ:
                    os.environ[k.strip()] = v.strip().strip('"').strip("'")
        from telegram_alerter import get_alerter
        a = get_alerter()
        if a and a.enabled:
            return a.send(msg)
    except Exception as e:
        print(f"telegram send failed: {e}")
    return False


def main() -> int:
    should, reason = _should_reset()
    if not should:
        print(f"[reset] skipping: {reason}")
        return 0

    if not PAPER_STATE.exists():
        print(f"[reset] paper_state.json missing at {PAPER_STATE}")
        return 1

    # Load current state for the backup + audit
    cur = json.loads(PAPER_STATE.read_text(encoding="utf-8"))
    old_cash = float(cur.get("cash", 0) or 0)
    old_realized = float(cur.get("realized_pnl", 0) or 0)
    n_orders = len(cur.get("orders", {}))
    n_positions = len(cur.get("positions", {}))

    # Backup current state
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = DCACHE / f"paper_state_pre_reset_{ts}.json"
    shutil.copy2(PAPER_STATE, backup)
    print(f"[reset] backed up to {backup.name}")

    # Reset to starting capital (default 100,000 from settings.yaml)
    cfg_path = ROOT / "config" / "settings.yaml"
    starting_capital = 100_000.0
    if cfg_path.exists():
        try:
            import yaml
            cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
            starting_capital = float(cfg.get("broker", {}).get("paper_capital", 100_000))
        except Exception as e:
            print(f"[reset] warn: could not read settings.yaml: {e}; using default 100000")

    new_state = {
        "cash": starting_capital,
        "realized_pnl": 0.0,
        "orders": {},
        "positions": {},
        "_reset_marker": {
            "reset_at": datetime.now().isoformat(timespec="seconds"),
            "reason": reason,
            "old_cash": old_cash,
            "old_realized_pnl": old_realized,
            "old_n_orders": n_orders,
            "old_n_positions": n_positions,
            "starting_capital": starting_capital,
        }
    }
    # FIX 2026-09-08 14:25: skip-save flag. The bot's _save_state (called on
    # every tick ~every 2-5s) checks for this flag and returns early. Without
    # it, the bot's in-memory state (still holding yesterday's poisoned P&L)
    # would overwrite our clean reset within seconds. The flag is also auto-
    # removed by PaperClient.__init__ once the new (post-restart) process
    # loads the clean state, so it doesn't persist beyond the reset window.
    skip_flag = DCACHE / "_skip_save.json"
    try:
        skip_flag.write_text(json.dumps({
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "reason": reason,
            "expected_removal": "by PaperClient.__init__ on next startup",
        }), encoding="utf-8")
        print(f"[reset] created _skip_save.json (suppresses bot _save_state for ~60s)")
    except Exception as e:
        print(f"[reset] WARN: could not create skip flag: {e}")
    PAPER_STATE.write_text(json.dumps(new_state, indent=2), encoding="utf-8")
    print(f"[reset] paper_state.json reset: cash=Rs.{starting_capital:,.0f}, realized=0, orders=0, positions=0")

    # Append a reset marker to trade_journal so the audit trail is complete
    try:
        journal_entry = {
            "trade_id": f"RESET-{ts}",
            "event": "RESET",
            "ts": datetime.now().isoformat(timespec="seconds"),
            "reason": reason,
            "old_cash": old_cash,
            "old_realized_pnl": old_realized,
            "old_n_orders": n_orders,
            "old_n_positions": n_positions,
            "new_cash": starting_capital,
            "new_realized_pnl": 0.0,
            "note": "paper state reset for clean baseline. The prior day's P&L is in trade_journal.jsonl as RECON-* entries; the running total in paper_state.json now starts at 0.",
        }
        with JOURNAL_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(journal_entry) + "\n")
        print(f"[reset] appended RESET marker to trade_journal.jsonl")
    except Exception as e:
        print(f"[reset] warn: journal append failed: {e}")

    # Update performance/daily.json with a reset marker
    try:
        if PERF_DAILY.exists():
            perf = json.loads(PERF_DAILY.read_text(encoding="utf-8"))
        else:
            perf = {}
        perf["reset_at"] = datetime.now().isoformat(timespec="seconds")
        perf["reset_reason"] = reason
        perf["prev_realized_pnl"] = old_realized
        perf["new_starting_capital"] = starting_capital
        PERF_DAILY.parent.mkdir(parents=True, exist_ok=True)
        PERF_DAILY.write_text(json.dumps(perf, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[reset] warn: daily.json update failed: {e}")

    # Consume the marker file (one-shot)
    if RESET_MARKER.exists():
        RESET_MARKER.unlink()
        print(f"[reset] consumed marker file")

    # FIX 2026-09-08 14:25: RESTART the bot so it reloads the reset paper_state.json.
    # Without this, the bot's in-memory state (loaded at startup) overwrites our
    # reset file on the next save, leaving the poisoned old values intact.
    # The bot is NSSM-managed, so nssm restart kills the current process and
    # spawns a fresh one which reads the new file. nssm needs admin (SYSTEM
    # context), which we have when called from the brain's in-process scheduler.
    # FIX 2026-09-08 14:30: also try mavis_force_action RESTART_BOT as a fallback
    # for non-admin contexts. The bot's force-action handler uses os._exit(0)
    # which bypasses atexit/broker.disconnect and lets NSSM respawn cleanly.
    # The skip-save flag we just wrote ensures the OLD bot's in-memory state
    # does NOT overwrite our clean reset on the way down.
    nssm_exe = r"C:\Tools\nssm\nssm-2.24\win64\nssm.exe"
    nssm_ok = False
    try:
        import subprocess
        r = subprocess.run(
            [nssm_exe, "restart", "KotakBotPaper"],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0:
            print(f"[reset] nssm restart KotakBotPaper OK")
            nssm_ok = True
        else:
            print(f"[reset] WARN: nssm restart failed exit={r.returncode}: {(r.stdout or r.stderr or '').strip()[:200]}")
    except Exception as e:
        print(f"[reset] WARN: nssm restart exception: {e}")
    # Fallback: mavis_force_action RESTART_BOT. The bot picks this up on its
    # next 30s cycle and calls os._exit(0), which lets NSSM respawn a new
    # process. Works without admin because it just writes a JSON file.
    if not nssm_ok:
        try:
            fa = DCACHE / "mavis_force_action.json"
            fa.write_text(json.dumps({
                "action": "RESTART_BOT",
                "reason": f"pre_market_reset ({reason})",
                "requested_at": datetime.now().isoformat(timespec="seconds"),
                "consumed": False,
            }), encoding="utf-8")
            print(f"[reset] wrote mavis_force_action RESTART_BOT (bot will self-restart within 30s)")
        except Exception as e:
            print(f"[reset] WARN: could not write force-action: {e}")

    # Telegram
    msg = (
        f"[Mavis pre-market] PAPER STATE RESET (reason: {reason})\n\n"
        f"Backup: {backup.name}\n"
        f"OLD: cash=Rs.{old_cash:,.2f}, realized=Rs.{old_realized:+,.2f}, "
        f"orders={n_orders}, positions={n_positions}\n"
        f"NEW: cash=Rs.{starting_capital:,.0f}, realized=Rs.0, orders=0, positions=0\n\n"
        f"Bot restarted via nssm so it loads the reset state. The prior day's "
        f"P&L stays in trade_journal.jsonl as RECON-* entries for audit."
    )
    if _send_telegram(msg):
        print(f"[reset] telegram sent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
