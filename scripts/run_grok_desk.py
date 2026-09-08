"""run_grok_desk.py — one-shot runner for the Grok Bot Desk.

Usage:
    python scripts/run_grok_desk.py              # run once, exit
    python scripts/run_grok_desk.py --loop 900   # run every 900s
    python scripts/run_grok_desk.py --dry-run    # don't send Telegram

Wired into daily_autonomy.py or cron if desired. The desk is meant to run
alongside the existing LLM brain as a parallel "second opinion" — not to
replace it. Default cadence: every 15 minutes during market hours.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))


def main() -> int:
    p = argparse.ArgumentParser(description="Run the Grok Bot Desk (6-role LLM system).")
    p.add_argument("--loop", type=int, default=0,
                   help="If > 0, run in a loop every N seconds (default 0 = run once and exit).")
    p.add_argument("--dry-run", action="store_true",
                   help="Skip Telegram alerts (only run the LLM cycle and save state).")
    p.add_argument("--no-save", action="store_true",
                   help="Skip state save (for ad-hoc calls).")
    args = p.parse_args()

    from scripts import grok_desk  # noqa: E402

    if args.loop > 0:
        while True:
            out = grok_desk.run_desk()
            if not args.no_save:
                grok_desk.save_state(out)
            if not args.dry_run and grok_desk.should_alert(out.head):
                grok_desk.send_telegram_alert(out)
            print(f"[grok_desk] {out.cycle_ts}  duration={out.duration_sec}s  head={out.head[:80]!r}")
            time.sleep(args.loop)
    else:
        out = grok_desk.run_desk()
        if not args.no_save:
            grok_desk.save_state(out)
        if not args.dry_run and grok_desk.should_alert(out.head):
            grok_desk.send_telegram_alert(out)
        print(f"[grok_desk] {out.cycle_ts}  duration={out.duration_sec}s  head={out.head[:200]!r}")
        if out.error:
            print(f"[grok_desk] errors:\n{out.error}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
