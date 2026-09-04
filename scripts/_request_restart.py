"""_request_restart.py - trigger self-restart of bot and/or brain via mavis_force_action.

FIX 2026-09-04 12:40: when new code is committed, the bot/brain pick it up only on
restart. This script writes a RESTART_BOT action to mavis_force_action.json so
the bot's main loop (when on the new code) will sys.exit(0) cleanly, and NSSM
auto-respawns with the latest code.

For the brain, we write a similar restart marker to a brain-specific file
(data_cache/quant_service_restart.json). The brain's watch loop reads it on
every cycle and exits if the marker is present, causing NSSM to auto-respawn.

Usage:
  python _request_restart.py bot       # restart just the bot
  python _request_restart.py brain     # restart just the brain
  python _request_restart.py both      # restart both (default)
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()

target = (sys.argv[1] if len(sys.argv) > 1 else "both").strip().lower()
now = datetime.now().isoformat()

if target in ("bot", "both"):
    fa = {
        "ts": now,
        "action": "RESTART_BOT",
        "reason": f"_request_restart.py at {now}: restart bot to load new code",
        "consumed": False,
    }
    p = ROOT / "data_cache" / "mavis_force_action.json"
    p.write_text(json.dumps(fa, indent=2), encoding="utf-8")
    print(f"  wrote {p}: action=RESTART_BOT")

if target in ("brain", "both"):
    rb = {
        "ts": now,
        "reason": f"_request_restart.py at {now}: restart brain to load new code",
        "consumed": False,
    }
    p2 = ROOT / "data_cache" / "quant_service_restart.json"
    p2.write_text(json.dumps(rb, indent=2), encoding="utf-8")
    print(f"  wrote {p2}: brain restart marker")

print()
print(f"  Requested restart: {target}")
print(f"  Bot/brain on NEW code: when next cycle runs (5-30s for bot, 30-60s for brain)")
print(f"  NSSM will auto-respawn. Total downtime: ~10-30s.")
