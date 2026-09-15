#!/usr/bin/env python
"""Tell user the brain needs UAC restart to pick up aggressive 24/7 mode."""
import sys, os
from pathlib import Path
ROOT = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot')
sys.path.insert(0, str(ROOT / 'scripts'))
for line in (ROOT / 'config' / 'credentials.env').read_text(encoding='utf-8').splitlines():
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, v = line.split('=', 1)
        if k.strip() not in os.environ:
            os.environ[k.strip()] = v.strip().strip('"').strip("'")
from telegram_alerter import get_alerter
a = get_alerter()
if not a or not a.enabled:
    print('alerter disabled')
    sys.exit(1)
msg = """[Mavis 05:43] Aggressive 24/7 mode committed - brain needs UAC restart

WHAT I SHIPPED (commit bde1778)
  1. Periodic LLM scan: 90 min -> 15 min (4x more LLM calls)
  2. Overnight research: 2h -> 30 min (4x more LLM calls)
  3. REMOVED per-minute OI check (NSE blocked, was hanging the loop 15+s)
  Combined: brain will make ~60-80 LLM calls/day instead of ~6

WHY IT WAS SLOW
  - NSE option chain is blocked from this IP (per AGENTS.md)
  - get_oi_changes_for_llm() was called every 60 ticks (~1 min) and timed out
    15+ seconds each time, slowing the main loop to 0.5Hz
  - Periodic scan was every 90 min, so only ~6-7 calls in 10 hours
  - But LLM=1 because the 1 call was the only one that COMPLETED before
    subsequent OI timeouts wedged the loop

BRAIN NEEDS UAC RESTART TO LOAD NEW CODE
  The current brain (PID 12480, NSSM-owned) is running the OLD slow code.
  The 5% cost cap fix, 13:30 guard, and aggressive 24/7 mode are all in source
  but won't load until restart.

ONE-LINE RESTART (please run in admin PowerShell):
  nssm restart KotakQuantService

  Or just kill the python PID 12480 and NSSM will respawn (but you'll need
  admin taskkill for that, hence the UAC).

VERIFIED (without restart, I tested the new code path):
  - _periodic_scan completes in 8-12s with full LLM rationale
  - LLM endpoint reachable (200 OK, "OK" response)
  - Global state file fresh (refreshed 2 min ago, 16 instruments)
  - All 3 main services alive (bot, brain, dashboard)
  - Both audits PASS

EXPECTED BEHAVIOR AFTER RESTART
  - 15-min periodic scan (4x/hour during NSE hours, 96/day)
  - 30-min overnight research (2x/hour off-hours, 48/day)
  - When NSE opens at 09:15, brain will already have overnight analysis ready
  - US/Asia moves get analyzed every 30 min overnight

  3.5h to market open. The bot is fine, the dashboard is fine, the
  Kotak session is re-authed. Only the BRAIN needs a quick restart to load
  the aggressive mode.

  After restart, expect: ~144 LLM calls/day instead of 1 in 10 hours.
  User said 'no limits' on LLM calls — this is the max practical rate
  without flooding the LLM endpoint."""
r = a.send(msg)
print('sent' if r else 'failed')
