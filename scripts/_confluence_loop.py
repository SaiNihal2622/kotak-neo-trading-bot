"""_confluence_loop.py - background loop that detects confluence and updates brain.

FIX 2026-09-04 12:25: the bot's BIAS_OVERRIDE handler reads mavis_force_action.json.
This script runs in a loop, detects confluence via _confluence_check, and writes
the override action every 5 minutes during market hours.

Start this in the background:
  Start-Process pythonw -ArgumentList "_confluence_loop.py" -WindowStyle Hidden
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

# Run every 5 min during market hours
INTERVAL_SEC = 300


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


def run():
    last_override = None
    while True:
        try:
            if is_market_hours():
                from scripts._confluence_check import find_confluence, load_global_state, write_force_action
                state = load_global_state()
                result = find_confluence(state) if state else None
                if result:
                    direction, count, evidence = result
                    sig = f"{direction}:{count}:{evidence[:40]}"
                    if sig != last_override:
                        # Write to mavis_force_action.json for bot to pick up
                        payload = write_force_action(direction, count, evidence)
                        print(f"[{datetime.now().isoformat()}] CONFIRMED: {sig}")
                        last_override = sig
                    else:
                        print(f"[{datetime.now().isoformat()}] (same as before, no rewrite)")
                else:
                    last_override = None
                    print(f"[{datetime.now().isoformat()}] no confluence")
            else:
                last_override = None
        except Exception as e:
            print(f"[{datetime.now().isoformat()}] error: {e}")
        time.sleep(INTERVAL_SEC)


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        pass
