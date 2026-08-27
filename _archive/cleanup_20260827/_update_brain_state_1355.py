#!/usr/bin/env python3
"""One-shot updater for brain_state.json at 13:55 tick."""
import json
import sys
from collections import OrderedDict
from pathlib import Path

STATE_PATH = Path(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json")

with open(STATE_PATH, "r", encoding="utf-8") as f:
    state = json.load(f, object_pairs_hook=OrderedDict)

# Update call_count_today
state["call_count_today"] = 57

# Build new last_decision
new_last = OrderedDict()
new_last["ts"] = "2026-08-25T08:25:00Z"
new_last["ist_time"] = "2026-08-25 13:55:00"
new_last["bias"] = "cautious"
new_last["source"] = "mavis"
new_last["max_positions"] = 2
new_last["actions"] = []
new_last["note"] = "HOLD_ALL_STATE_MATERIALLY_IMPROVED_NIFTY_24166_BN_57386_BN_BACK_ABOVE_57350_trigger_+35.7pts_PE_spread_unwound_from_100_max_loss_to_~14_NIFTY_50.9pts_above_24115_trigger_CE_57600_214.30_OTM_safe_35min_to_force_square_14_30_post_13_30_no_new_entries_executor_dead_3d"
new_last["reasoning"] = (
    "Tick at 13:55 IST on Tue 2026-08-25 [0DTE MONTHLY expiry day]. 25 min after 13:30 entry cutoff tick, "
    "295 min into regular session, 1h20m to 15:15 square-off, 35 min to 14:30 force-square. Market in regular session. "
    "VIX 11.22 [calm, <12, range-bound regime confirmed]. Range regime confirmed for both underlyings [NIFTY conf=0.7 "
    "range=0.34%, BANKNIFTY conf=0.7 range=0.74%]. Macro: no events next 7d, no blackout. Research: still unavailable "
    "[45th consecutive tick]. Live positions: 2 strategies [NIFTY IB + BANKNIFTY IC] at max_positions=2. "
    "KEY STATE vs 13:50 tick: MASSIVE RECOVERY. NIFTY +32.40 pts from 24133.50 to 24165.90 (last 13:55:13 refresh). "
    "NIFTY 50.90 above 24115 hard trigger (was 18.50 above, WIDENED 32.40 - much safer). NIFTY 65.90 above 24100 PE strike "
    "(was 33.50 above, WIDENED 32.40). NIFTY short 24300 CE 134.10 OTM (was 166.50 OTM, NARROWED 32.40 by NIFTY rise). "
    "BN +92.00 pts from 57293.70 to 57385.70 (huge bounce). BN 35.70 above 57350 hard trigger (was 56.30 BELOW, RECROSSED ABOVE - 92pt bounce cleared trigger). "
    "BN short 57400 PE 14.30 ITM (was 106.30 ITM, IMPROVED 92.00 by BN rise). BN long 57300 PE OTM (was 6.30 ITM, IMPROVED 6.30 - now safely OTM). "
    "PE SPREAD INTRINSIC = 14.30 (was 100 = FULL MAX LOSS, UNWOUND 85.70 pts). This means PE spread no longer at max loss - significant recovery. "
    "57300 wing 85.70 pts above (was 6.30 BREACHED, RECOVERED 92.00 - back to safe). CE side 57600 214.30 OTM (was 306.30 OTM, NARROWED 92.00 by BN rise - but still 214 OTM = safe, no hard trigger). "
    "NIFTY CE 24300 134.10 OTM (was 166.50, narrowed 32.40 - still safe). VIX 11.22 (was 11.33, -0.11 - more calm). "
    "UNREALIZED PNL [live est at 13:55]: NIFTY IB roughly flat to slightly better (~+1800 INR, PE buffer widened 32 pts adding ~1200 INR, "
    "CE narrowed 32 pts costing ~1000 INR, net +200 INR). BN IC IMPROVED significantly: PE spread unwound from 100 to 14.30 = +85.70 pts * 30 = +2571 INR improvement on PE side. "
    "CE side narrowed 92 pts - short 57600 CE ~+1500 INR cost, long 57700 CE ~+750 INR gain (lower delta), net CE ~-750 INR. "
    "Net BN IC: from -1300 to ~+520 INR (improvement ~+1820 INR). TOTAL ~+2320 INR [up ~1820 from +500 at 13:50]. "
    "DECISION: CONTINUE HOLD ALL [57th tick of day]. Rationale: State IMPROVED materially from 13:50. NIFTY well clear of 24115 trigger (50.9 above). "
    "BN RECROSSED 57350 trigger band (35.7 above). PE spread unwound from max loss (now 14.30). All triggers cleared. "
    "No reason to do anything manual - 0DTE monthly, 35 min to force-square backstop, 1h20m to 15:15, both positions are theta-positive. "
    "Re-emitting CLOSE has no effect (executor dead 3d). Force-square at 14:30 is the working exit. "
    "LESSON: on 0DTE monthly, intraday swings of +/-100pts on BN are common near expiry. PE spread at full max loss at 13:50 was alarming but reversible on bounce. "
    "KEY INSIGHT: the bot would have been better off NOT having a hard trigger that fires irreversible damage signals - 92pt intraday swings make hard triggers noisy. "
    "NEXT TICK TRIGGERS: BN<57250 sustained = re-check if PE side re-locks; NIFTY<24115 sustained = close NIFTY IB PE; force-square at 14:30 closes both legs of both strategies."
)

new_last["candle_regime_evidence"] = OrderedDict()
new_last["candle_regime_evidence"]["NIFTY"] = OrderedDict([
    ("regime", "range"),
    ("confidence", 0.7),
    ("reason", "range=0.34% tight + vix=11.2 low"),
    ("5d_change_pct", 0.36),
    ("range_pct", 0.34),
    ("today_move_pts", -10.6),
])
new_last["candle_regime_evidence"]["BANKNIFTY"] = OrderedDict([
    ("regime", "range"),
    ("confidence", 0.7),
    ("reason", "range=0.74% tight + vix=11.2 low"),
    ("5d_change_pct", 0.25),
    ("range_pct", 0.74),
    ("today_move_pts", 25.2),
])

new_last["macro_evidence"] = OrderedDict([
    ("in_blackout", False),
    ("next_event", None),
    ("events_next_7d", []),
])

new_last["research_evidence"] = OrderedDict([
    ("available", False),
    ("note", "research not available [Kotak PDF download failed, 45th consecutive tick], skipped research bias"),
])

new_last["monday_brief_evidence"] = OrderedDict([
    ("applicable", False),
    ("note", "Tuesday - Monday brief not consulted"),
])

new_last["position_evidence"] = []
pe1 = OrderedDict()
pe1["strategy"] = (
    "NIFTY Iron Butterfly [HOLD - NIFTY 24165.90 UP 32.40pts from 13:50. 65.90 above 24100 PE strike (WIDENED 32.40 from 33.50). "
    "50.90 above 24115 hard trigger (WIDENED 32.40 from 18.50 - much safer). Short 24300 CE 134.10 OTM (NARROWED 32.40 by NIFTY rise, still safe). "
    "Long 24000 PE 165.90 OTM (WIDENED 32.40). Both buffers safe, theta working well into close.]"
)
pe1["spot"] = 24165.9
pe1["distance_to_short_ce_pts"] = 134.1
pe1["distance_to_short_pe_pts"] = 65.9
pe1["distance_to_wing_ce_pts"] = 234.1
pe1["distance_to_wing_pe_pts"] = 165.9
pe1["expiry"] = "2026-08-25"
pe1["0dte"] = True
pe1["monthly_expiry"] = True
pe1["net_credit"] = 3767.25
pe1["max_loss"] = 3732.75
pe1["unrealized_pnl_inr"] = 1800.0
pe1["pct_of_max_profit"] = 48.2
pe1["status"] = "CE_134.10pts_OTM_GREEN_PE_65.90pts_OTM_GREEN_NIFTY_24165.90_bounced_32.40pts_50.90pts_above_24115_hard_trigger_WIDENED_from_18.50_unrealized_+1800_HOLD_force_square_14_30_35min"
pe1["tight_side_watch"] = "PE_24100_65.90pts_OTM_50.90pts_above_24115_close_trigger_safest_in_30min_CE_24300_134.10pts_OTM_safe_narrowed_32.40"
new_last["position_evidence"].append(pe1)

pe2 = OrderedDict()
pe2["strategy"] = (
    "BANKNIFTY Iron Condor [HOLD - STATE IMPROVED MATERIALLY. BN 57385.70 UP 92pts from 13:50. "
    "BN 35.70 above 57350 hard trigger (was 56.30 BELOW, RECROSSED +92.00). Short 57400 PE 14.30 ITM (was 106.30 ITM, IMPROVED 92.00). "
    "Long 57300 PE OTM (was 6.30 ITM, RECOVERED 6.30 - now safe). PE SPREAD INTRINSIC = 14.30 (was 100 = FULL MAX LOSS, UNWOUND 85.70 - significant recovery). "
    "57300 wing 85.70 pts above (was 6.30 BREACHED, RECOVERED 92.00 - safely OTM). CE side 57600 214.30 OTM (NARROWED 92.00 by BN rise - still 214 OTM safe).]"
)
pe2["spot"] = 57385.7
pe2["distance_to_short_ce_pts"] = 214.3
pe2["distance_to_short_pe_pts"] = -14.3
pe2["distance_to_wing_ce_pts"] = 314.3
pe2["distance_to_wing_pe_pts"] = 85.7
pe2["expiry"] = "2026-08-25"
pe2["0dte"] = True
pe2["monthly_expiry"] = True
pe2["net_credit"] = 2325.3
pe2["max_loss"] = 3674.7
pe2["unrealized_pnl_inr"] = 520.0
pe2["pct_of_max_profit"] = 14.2
pe2["status"] = "STATE_IMPROVED_MATERIALLY_BN_57385.70_bounced_92pts_PE_spread_UNWOUND_from_100_to_14.30_intrinsic_57300_wing_RECOVERED_85.70pts_above_short_57400_PE_14.30_ITM_CE_214.30_OTM_safe_force_square_14_30_35min"
pe2["tight_side_watch"] = "PE_57300_wing_85.70pts_above_RECOVERED_from_breach_short_57400_PE_14.30_ITM_PE_spread_14.30_unwound_from_100_CE_57600_214.30_OTM_safe_narrowed_92pts"
new_last["position_evidence"].append(pe2)

new_last["executor_status"] = OrderedDict([
    ("standalone_executor", "dead_3d_no_orders_since_2026-08-22"),
    ("in_process_resilient", "not_processing_brain_actions"),
    ("force_square_backstop", "14_30_IST_35min_away"),
    ("working_exit", "force_square_only"),
])

new_last["tick_summary_13_55"] = (
    "57th tick of day, CONTINUE HOLD ALL. Bias=cautious. STATE IMPROVED MATERIALLY vs 13:50. NIFTY +32.40pts from 24133.50 to 24165.90. "
    "NIFTY 50.90 above 24115 trigger (WIDENED 32.40 from 18.50 - much safer). NIFTY CE 24300 134.10 OTM (NARROWED 32.40 - still safe). "
    "BN +92.00pts from 57293.70 to 57385.70. BN 35.70 above 57350 trigger (was 56.30 BELOW, RECROSSED ABOVE +92pt bounce). "
    "BN PE SPREAD INTRINSIC UNWOUND from 100 to 14.30 (recovered 85.70pts from max loss). 57300 wing 85.70pts above (RECOVERED 92.00pts from breach). "
    "CE side 57600 214.30 OTM (NARROWED 92.00 - still safe). VIX -0.11 to 11.22. UNREALIZED PNL est: NIFTY IB +1800 INR, BN IC +520 INR [up +1820 from -1300 at 13:50]. "
    "TOTAL ~+2320 INR. LESSON: 92pt intraday BN swings are COMMON on 0DTE monthly expiry. The 13:50 PE-spread-at-100-max-loss signal was NOISE - "
    "by 13:55 it had unwound 85.70pts. Hard triggers firing irreversible damage signals on 0DTE monthly are too noisy. "
    "Force-square at 14:30 is the only working exit (executor dead 3d). REASON FOR HOLD: 0DTE theta-positive, all triggers cleared, 35 min to force-square backstop. "
    "NEXT TICK TRIGGERS: BN<57250 sustained = re-check PE side; NIFTY<24115 sustained = close NIFTY IB PE; force-square at 14:30 closes both legs of both strategies."
)

new_last["timestamp"] = "2026-08-25T08:25:00Z"
new_last["confidence"] = 0.7
new_last["risk_budget_pct"] = 0.0
new_last["rationale"] = (
    "HOLD ALL - STATE IMPROVED MATERIALLY since 13:50. NIFTY 50.9 above 24115 trigger (was 18.5). "
    "BN 35.7 above 57350 trigger (was 56.3 below). PE spread unwound from 100 max loss to 14.30 (recovery 85.70pts). "
    "57300 wing 85.7 above (was 6.3 breached). 0DTE monthly, 35 min to force-square 14:30 backstop, 1h20m to 15:15. "
    "All triggers cleared, no manual action needed."
)

state["last_decision"] = new_last

# Append new history entry
new_history = OrderedDict()
new_history["ist_time"] = "2026-08-25 13:55:00"
new_history["bias"] = "cautious"
new_history["note"] = "0dte_monthly_hold_STATE_MATERIALLY_IMPROVED_NIFTY_24166_+32pts_BN_57386_+92pts_back_above_57350_trigger_PE_spread_unwound_100_to_14.30_57300_wing_recovered_85.7pts_NIFTY_buffer_50.9_above_24115_force_square_14_30_35min_backstop_executor_dead_3d_unrealized_+2320INR"
new_history["actions"] = []

state["history"] = list(state.get("history", [])) + [new_history]

# Write back
with open(STATE_PATH, "w", encoding="utf-8") as f:
    json.dump(state, f, ensure_ascii=False, indent=2)

print(f"Updated brain_state.json successfully")
print(f"call_count_today: {state['call_count_today']}")
print(f"last_decision.ist_time: {state['last_decision']['ist_time']}")
print(f"last_decision.bias: {state['last_decision']['bias']}")
print(f"history entries: {len(state['history'])}")
