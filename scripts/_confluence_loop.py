"""_confluence_loop.py - background loop that detects confluence and updates brain.

FIX 2026-09-04 12:25: the bot's BIAS_OVERRIDE handler reads mavis_force_action.json.
This script runs in a loop, detects confluence via _confluence_check, and writes
the override action every 5 minutes during market hours.

FIX 2026-09-04 13:00: previous version died after 5 min because print() didn't flush
and the script's stdout was buffered when launched with pythonw. Now uses:
- sys.stdout.flush() after each print
- logging.basicConfig with FileHandler (writes to Logs/_confluence_loop.log)
- Keeps a heartbeat file (data_cache/_confluence_loop.heartbeat) so the
  premarket_self_heal can verify it's running

Start this in the background:
  Start-Process pythonw -ArgumentList "_confluence_loop.py" -WindowStyle Hidden
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

# Run every 5 min during market hours
INTERVAL_SEC = 300
HEARTBEAT_PATH = ROOT / "data_cache" / "_confluence_loop.heartbeat"
LOG_PATH = ROOT / "Logs" / "_confluence_loop.log"

# FIX 2026-09-04 13:00: configure logging to file (pythonw doesn't show stdout).
# Without this, the previous version's print() output was buffered and the
# script appeared dead even when it was running.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    handlers=[
        logging.FileHandler(str(LOG_PATH), mode="a", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),  # also goes to console if visible
    ],
)
log = logging.getLogger("confluence_loop")


def is_market_hours() -> bool:
    """Approx NSE market hours 09:15 - 15:30 IST."""
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    h, m = now.hour, now.minute
    if h < 9 or (h == 9 and m < 15):
        return False
    if h > 15 or (h == 15 and m > 30):
        return False
    return True


def write_heartbeat():
    """Write a heartbeat file so external monitors know we're alive."""
    try:
        HEARTBEAT_PATH.write_text(
            json.dumps({"ts": datetime.now().isoformat(), "pid": os.getpid()}),
            encoding="utf-8",
        )
    except Exception:
        pass


def run():
    last_override = None
    iterations = 0
    while True:
        iterations += 1
        try:
            write_heartbeat()
            if is_market_hours():
                from scripts._confluence_check import (
                    find_confluence, load_global_state, write_force_action,
                )
                state = load_global_state()
                result = find_confluence(state) if state else None
                if result:
                    direction, count, evidence = result
                    sig = f"{direction}:{count}:{evidence[:40]}"
                    if sig != last_override:
                        payload = write_force_action(direction, count, evidence)
                        log.info(f"CONFIRMED: {sig}")
                        last_override = sig
                    else:
                        log.info("(same as before, no rewrite)")
                else:
                    last_override = None
                    log.info("no confluence")
            else:
                last_override = None
                if iterations % 12 == 1:  # log every hour when not in market
                    log.info("outside market hours, waiting")
        except Exception as e:
            log.error(f"error: {e}")
        # Sleep in small chunks so we can be killed quickly
        for _ in range(INTERVAL_SEC):
            time.sleep(1)
            # Keep heartbeat fresh every 30s
            if _ % 30 == 29:
                write_heartbeat()


if __name__ == "__main__":
    log.info(f"starting confluence_loop (pid={os.getpid()})")
    try:
        run()
    except KeyboardInterrupt:
        log.info("stopped by user")

