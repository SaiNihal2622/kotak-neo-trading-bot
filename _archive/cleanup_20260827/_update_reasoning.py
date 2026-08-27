#!/usr/bin/env python3
"""Update the reasoning field in brain_state.json after force-square fire."""
import json
from pathlib import Path

path = Path(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json")

with path.open("r", encoding="utf-8") as f:
    state = json.load(f)

new_reasoning = (
    "Tick at 14:30 IST on Tue 2026-08-25 [0DTE MONTHLY expiry day - INTRADAY SQUARE-OFF WINDOW]. "
    "60 min after 13:30 entry cutoff, 390 min into regular session, AT 14:30 force-square mark, "
    "45 min to 15:15. **CRITICAL STATE CHANGE vs 14:25 tick: FORCE-SQUARE FIRED at 14:30:03-04 by the in-process paper executor** "
    "('force-closed 2 open trades (force_square_off_time hit)' WARNING in bot.log). "
    "All 2 ICs force-closed: NIFTY IC PE side filled (BUY 65x 24100PE @ 44.82, SELL 65x 24000PE @ 19.39), "
    "BN IC PE side filled (BUY 30x 57400PE @ 193.62, SELL 30x 57300PE @ 147.06), "
    "BN IC CE side filled (BUY 30x 57600CE @ 106.34, SELL 30x 57700CE @ 76.58). "
    "open_positions now EMPTY []. cash 100229 INR, realized_pnl 229 INR. "
    "Live NIFTY 24177.55 (up 13.25pts from 24164.30 at 14:25). "
    "Live BN 57374.70 (up 24pts from 57350.70 at 14:25 - mean-reverted ABOVE 57350 trigger zone, "
    "ironic given the whipsaw worry 5 min ago). "
    "VIX 11.20 (calm, <12, range regime confirmed). "
    "Range regime both underlyings [NIFTY conf=0.7 range=0.34%, BANKNIFTY conf=0.7 range=0.74%]. "
    "Macro: no events, no blackout. Research: still unavailable. "
    "PnL of force-square: est realized from fills: NIFTY IC PE spread -> small gain/loss; "
    "BN IC CE spread -> small gain; BN IC PE spread (57400PE ITM ~50pts forced buyback @ 193.62) -> "
    "HEAVY LOSS on the 57400PE leg, the long 57300PE @ 147.06 covers some of it. "
    "The morning credit captured was NIFTY IC +3264.95 + BN IC +2325.30 = +5590.25 INR. "
    "The realized PnL of 229 in the state suggests the net P&L after all closes is barely positive. "
    "DAY PnL ~+229 INR on 100k capital = +0.23% (small positive day, after taking ~+5000 INR loss on the BN PE side forced buyback). "
    "DECISION: HOLD ALL [64th tick of day, call_count_today=63]. No positions to manage. "
    "No new entries (post 13:30 cutoff). Strategy exhausted for the day. "
    "NEXT TICK TRIGGERS: (1) EOD at 15:15 - market close. (2) Manual review of day PnL. "
    "(3) Prepare for tomorrow Wed 2026-08-26. "
    "KEY INSIGHT: the in-process executor's force_square_off_time backstop FIRED CORRECTLY "
    "despite the standalone executor being dead 3d. This is the safety net working as designed. "
    "Future sessions should trust the in-process resilient force-square logic at 14:30 IST as the primary 0DTE exit."
)

state["last_decision"]["reasoning"] = new_reasoning

with path.open("w", encoding="utf-8") as f:
    json.dump(state, f, ensure_ascii=False, indent=2)
    f.write("\n")

print("REASONING REPLACED OK")
print(f"New reasoning length: {len(new_reasoning)} chars")
