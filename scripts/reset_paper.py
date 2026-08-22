"""reset_paper.py — reset paper trading state for a clean Monday session.

Sets:
  - cash = Rs.100,000 (1L, starting capital)
  - realized_pnl = 0
  - positions = {}  (clears 14 phantom positions from Friday 8/20 + 8/21 expiries)
  - preserves orders[] history (audit trail of past paper trades)

Also resets brain_state.json (last_decision=None, history=[]) and
brain_actions.json (empty actions list) so the first Monday 09:00 tick
starts from a clean decision slate.

Backs up the current state to data_cache/paper_state_pre_reset_<ts>.json
before any mutation. Reports deltas to stdout and (optionally) Telegram.

Usage:
    python scripts/reset_paper.py             # reset only
    python scripts/reset_paper.py --send-tg    # reset + Telegram confirmation
    python scripts/reset_paper.py --dry-run    # show what would change, no writes
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
STATE = ROOT / "data_cache" / "paper_state.json"
BRAIN_STATE = ROOT / "data_cache" / "brain_state.json"
BRAIN_ACTIONS = ROOT / "data_cache" / "brain_actions.json"
INITIAL_CAPITAL = 100_000.0


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _save(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")


def send_telegram(msg: str) -> bool:
    """Send a Telegram via curl.exe. Returns True on success."""
    try:
        import subprocess
        from dotenv import load_dotenv
        env_path = ROOT / "config" / "credentials.env"
        token = ""
        chat_id = ""
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith("TELEGRAM_BOT_TOKEN="):
                    token = line.split("=", 1)[1].strip().strip('"').strip("'")
                elif line.startswith("TELEGRAM_CHAT_ID="):
                    chat_id = line.split("=", 1)[1].strip().strip('"').strip("'")
        if not token or not chat_id:
            return False
        import tempfile
        tmp = Path(tempfile.gettempdir()) / f"tg_reset_{datetime.now().strftime('%H%M%S')}.txt"
        tmp.write_text(msg, encoding="utf-8")
        r = subprocess.run(
            ["curl.exe", "-s", "-X", "POST",
             f"https://api.telegram.org/bot{token}/sendMessage",
             "--data-urlencode", f"chat_id={chat_id}",
             "--data-urlencode", f"text@{tmp}"],
            capture_output=True, text=True, timeout=30, check=False,
        )
        try:
            tmp.unlink()
        except Exception:
            pass
        return r.returncode == 0 and '"ok":true' in r.stdout
    except Exception as e:
        print(f"[reset_paper] telegram failed: {e}", file=sys.stderr)
        return False


def compute_deltas(before: dict) -> dict:
    """Compute the deltas that will be applied. Returns a dict of before->after."""
    old_cash = float(before.get("cash", 0))
    old_pnl = float(before.get("realized_pnl", 0))
    old_positions = before.get("positions", {}) or {}
    n_open = sum(1 for p in old_positions.values() if p.get("qty", 0) != 0)
    return {
        "before": {
            "cash": old_cash,
            "realized_pnl": old_pnl,
            "open_positions": n_open,
            "total_positions": len(old_positions),
        },
        "after": {
            "cash": INITIAL_CAPITAL,
            "realized_pnl": 0.0,
            "open_positions": 0,
            "total_positions": 0,
        },
        "delta_cash": INITIAL_CAPITAL - old_cash,
        "delta_pnl": -old_pnl,
        "positions_cleared": n_open,
    }


def apply_reset(before: dict, deltas: dict) -> dict:
    """Mutate a copy of `before` with the reset values + reset metadata."""
    after = dict(before)  # shallow copy — preserves orders[] entirely
    after["cash"] = INITIAL_CAPITAL
    after["realized_pnl"] = 0.0
    after["positions"] = {}
    # Add a reset marker so the audit trail is clear
    after["_reset_history"] = after.get("_reset_history", [])
    after["_reset_history"].append({
        "ts": datetime.now().isoformat(),
        "type": "manual_paper_reset",
        "reason": "pre_monday_clean_state",
        "initial_capital": INITIAL_CAPITAL,
        "old_cash": deltas["before"]["cash"],
        "old_pnl": deltas["before"]["realized_pnl"],
        "old_open_positions": deltas["before"]["open_positions"],
        "new_cash": INITIAL_CAPITAL,
        "new_pnl": 0.0,
    })
    return after


def reset_brain_state() -> dict:
    """Reset brain_state.json — clear last_decision and history.
    Keep the file structure (today_date, call_count_today) for cron compatibility."""
    return {
        "today_date": "",
        "call_count_today": 0,
        "last_decision": None,
        "history": [],
    }


def reset_brain_actions() -> dict:
    """Reset brain_actions.json to a no-op HOLD placeholder."""
    return {
        "ts": datetime.now().isoformat(),
        "ist_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "bias": "neutral",
        "source": "mavis",
        "max_positions": 0,
        "actions": [],
        "note": "pre_monday_reset",
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="Show deltas only, no writes")
    p.add_argument("--send-tg", action="store_true", help="Send Telegram confirmation after reset")
    p.add_argument("--no-backup", action="store_true", help="Skip backup (NOT recommended)")
    args = p.parse_args()

    if not STATE.exists():
        print(f"[reset_paper] no state file at {STATE}", file=sys.stderr)
        return 1

    before = _load(STATE)
    deltas = compute_deltas(before)
    print("[reset_paper] DELTAS:")
    print(json.dumps(deltas, indent=2))
    if args.dry_run:
        print("[reset_paper] DRY-RUN — no writes")
        return 0

    # 1) Backup current state
    if not args.no_backup:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = STATE.parent / f"paper_state_pre_reset_{ts}.json"
        shutil.copy2(STATE, backup)
        print(f"[reset_paper] backed up to {backup.name}")

    # 2) Apply paper reset
    after = apply_reset(before, deltas)
    _save(STATE, after)
    print(f"[reset_paper] wrote {STATE.name}: cash={INITIAL_CAPITAL}, pnl=0, positions cleared ({deltas['positions_cleared']} phantoms)")

    # 3) Reset brain state + actions
    _save(BRAIN_STATE, reset_brain_state())
    print(f"[reset_paper] reset {BRAIN_STATE.name}")
    _save(BRAIN_ACTIONS, reset_brain_actions())
    print(f"[reset_paper] reset {BRAIN_ACTIONS.name}")

    # 4) Telegram confirmation
    if args.send_tg:
        msg = (
            "🔄 Paper state reset for Monday\n\n"
            f"Capital: Rs.{deltas['before']['cash']:,.2f} → Rs.{INITIAL_CAPITAL:,.2f} (delta Rs.{deltas['delta_cash']:+,.2f})\n"
            f"Realized P&L: Rs.{deltas['before']['realized_pnl']:+,.2f} → Rs.0.00\n"
            f"Open positions: {deltas['before']['open_positions']} → 0 (phantoms cleared)\n"
            f"Orders history: kept (full audit trail)\n"
            f"Brain state: reset (last_decision=None)\n"
            f"Brain actions: reset to HOLD\n\n"
            f"Backup: data_cache/paper_state_pre_reset_*.json\n"
            f"Ready for Mon 09:00 IST first live tick on the upgraded cron spec."
        )
        ok = send_telegram(msg)
        print(f"[reset_paper] telegram: {'sent' if ok else 'FAILED'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
