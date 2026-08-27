"""Rebuild brain_state.json with a properly-formed last_decision block."""
import json
import re

path = r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json'

# Construct the new last_decision as a Python dict (json.dumps will handle escaping)
new_last_decision = {
    "ts": "2026-08-25T08:55:00Z",
    "ist_time": "2026-08-25 14:25:00",
    "bias": "cautious",
    "source": "mavis",
    "max_positions": 2,
    "actions": [],
    "note": "HOLD_ALL_NIFTY_24164.30_+1.25pts_from_14_20_64.30_above_24100_PE_safe_49.30_above_24115_trigger_safe_short_24300_CE_135.70_OTM_safe_NARROWED_1.25_BN_57350.70_WHIPSAW-18.65pts_BACK_AT_57350_trigger_band_RETRACTED_FROM_57369.35_recovery_short_57400_PE_49.30_ITM_WORSENED_18.65_from_30.65_ITM_57300_PE_wing_buffer_50.70_OTM_NARROWED_18.65_from_69.35_STILL_OTM_safe_but_gamma_danger_zone_PE_spread_intrinsic_49.30_of_100_WIDENED_18.65_from_30.65_CE_57600_249.30_OTM_NARROWED_18.65_still_safe_5min_to_14:30_force_square_backstop_imminent_executor_dead_3d_manual_close_no_effect_let_force_square_close_0DTE_MONTHLY_expiry_max_gamma_risk_no_new_entries",
    "reasoning": (
        "Tick at 14:25 IST on Tue 2026-08-25 [0DTE MONTHLY expiry day]. "
        "55 min after 13:30 entry cutoff, 385 min into regular session, 5 min to 14:30 force-square, 50 min to 15:15. "
        "VIX 11.25-11.27 [calm, <12, range-bound confirmed]. "
        "Range regime both underlyings [NIFTY conf=0.7 range=0.34%, BANKNIFTY conf=0.7 range=0.74%]. "
        "Macro: no events, no blackout. Research: still unavailable. "
        "Live positions: 2 strategies [NIFTY IC + BN IC, both 100pt wide]. "
        "KEY STATE CHANGE vs 14:20 tick: BN WHIPSAWED -18.65pts in 5 min, from 57369.35 back to 57350.70. "
        "The 14:20 'recovery' was a 5-min bounce, NOT sustained. BN is back right AT the 57350 hard trigger band. "
        "CRITICAL DETAIL: (1) BN short 57400 PE WORSENED 18.65pts: now 49.30 ITM (was 30.65 ITM at 14:20). "
        "(2) BN long 57300 PE wing buffer NARROWED 18.65pts: now 50.70 OTM (was 69.35 at 14:20 - still OTM/safe but DANGEROUS gamma zone). "
        "(3) BN PE spread intrinsic REWIDENED to 49.30 of 100 (was 30.65 at 14:20). "
        "Max loss on PE only if BN<57250 (100.70pts below). "
        "(4) BN CE side 57600 249.30 OTM (NARROWED 18.65 from 230.65 at 14:20 - still very safe). "
        "(5) Long 57700 CE 349.30 OTM (deep green). "
        "NIFTY 24164.30: +1.25pts from 14:20 (basically flat). "
        "64.30 above 24100 PE strike (49.30 above 24115 hard trigger). "
        "Short 24300 CE 135.70 OTM. Long 24400 CE 235.70 OTM. Long 24000 PE 164.30 OTM. "
        "All NIFTY buffers SAFE, theta working. VIX 11.25-11.27 (flat low). "
        "UNREALIZED PNL [live est at 14:25]: NIFTY IC est PnL ~+1900 INR (flat - no change). "
        "BN IC: PE spread WIDENED 18.65pts at gamma heavy -1500 INR deterioration. "
        "CE narrowed 18.65pts -150 INR offset. BN IC est PnL ~-1750 INR (worse from -100 at 14:20, -1650 INR deterioration in 5 min). "
        "TOTAL est PnL: NIFTY +1900 + BN -1750 = +150 INR [down from +1800 at 14:20, -1650 INR in 5 min]. "
        "The BN whipsaw cost -1650 INR in 5 min. "
        "DECISION: CONTINUE HOLD ALL [63rd tick of day, call_count_today=62]. "
        "Rationale: (1) Executor dead 3d, only force-square at 14:30 works. "
        "(2) 5 min to 14:30 - force-square IMMINENT. "
        "(3) Even though BN whipsawed back to trigger, we are 5 min from force-square - manual close via brain_actions.json is a no-op (executor dead). "
        "(4) NIFTY fully safe. BN 57300 wing still 50.70 OTM (not breached). "
        "(5) Force-square at 14:30 closes both legs of both strategies at market. "
        "(6) PnL deterioration (-1650 INR) is recoverable at 14:30 force-square - won't get better by holding 5 more min but won't get worse either. "
        "NEXT TICK TRIGGERS: BN<57250 = full max loss on PE accept; NIFTY<24115 = NIFTY IC PE in trouble accept; "
        "force-square at 14:30 closes both legs of both strategies."
    ),
    "candle_regime_evidence": {
        "NIFTY": {
            "regime": "range",
            "confidence": 0.7,
            "reason": "range=0.34% tight + vix=11.3 low",
            "5d_change_pct": 0.35,
            "range_pct": 0.34,
            "today_move_pts": -10.6
        },
        "BANKNIFTY": {
            "regime": "range",
            "confidence": 0.7,
            "reason": "range=0.74% tight + vix=11.3 low",
            "5d_change_pct": 0.19,
            "range_pct": 0.74,
            "today_move_pts": 25.2
        }
    },
    "macro_evidence": {
        "in_blackout": False,
        "next_event": None,
        "events_next_7d": []
    },
    "research_evidence": {
        "available": False,
        "note": "research not available [Kotak PDF download failed, 51st consecutive tick], skipped research bias"
    },
    "monday_brief_evidence": {
        "applicable": False,
        "note": "Tuesday - Monday brief not consulted"
    },
    "position_evidence": [
        {
            "strategy": "NIFTY Iron Condor [HOLD - NIFTY 24164.30 +1.25pts from 14:20 (essentially flat). 64.30 above 24100 PE strike (49.30 above 24115 hard trigger - safe buffer). Short 24300 CE 135.70 OTM (NARROWED 1.25 - still very safe). Long 24400 CE 235.70 OTM (deep green). Long 24000 PE 164.30 OTM (deep green). All buffers safe, theta working well into close.]",
            "spot": 24164.30,
            "distance_to_short_ce_pts": 135.70,
            "distance_to_short_pe_pts": 64.30,
            "distance_to_wing_ce_pts": 235.70,
            "distance_to_wing_pe_pts": 164.30,
            "expiry": "2026-08-25",
            "0dte": True,
            "monthly_expiry": True,
            "net_credit": 3264.95,
            "max_loss": 3235.05,
            "unrealized_pnl_inr": 1900.0,
            "pct_of_max_profit": 58.7,
            "status": "PE_64.30pts_OTM_safe_49.30pts_above_24115_trigger_safe_CE_135.70pts_OTM_safe_NARROWED_1.25_force_square_14_30_5min",
            "tight_side_watch": "PE_24100_64.30pts_OTM_safe_CE_24300_135.70pts_OTM_safe"
        },
        {
            "strategy": "BANKNIFTY Iron Condor [HOLD - BN WHIPSAW -18.65pts in 5 min back to 57350.70 (from 57369.35). Back AT 57350 hard trigger band (recovered bounce was NOT sustained). Short 57400 PE 49.30 ITM (WORSENED 18.65 from 30.65 ITM). Long 57300 PE wing buffer 50.70 OTM (NARROWED 18.65 from 69.35 - STILL OTM safe but DANGEROUS gamma zone). PE SPREAD INTRINSIC = 49.30 of 100 (REWIDENED 18.65 from 30.65 - back in danger zone). Max loss only if BN<57250 (100.70pts below). CE side 57600 249.30 OTM (NARROWED 18.65 from 230.65 - still very safe). Long 57700 CE 349.30 OTM (deep green).]",
            "spot": 57350.70,
            "distance_to_short_ce_pts": 249.30,
            "distance_to_short_pe_pts": -49.30,
            "distance_to_wing_ce_pts": 349.30,
            "distance_to_wing_pe_pts": 50.70,
            "expiry": "2026-08-25",
            "0dte": True,
            "monthly_expiry": True,
            "net_credit": 2325.3,
            "max_loss": 1935.6,
            "unrealized_pnl_inr": -1750.0,
            "pct_of_max_profit": -90.3,
            "status": "BN_WHIPSAW_57350.70_dn_18.65pts_BACK_AT_57350_trigger_short_57400_PE_49.30pts_ITM_worsened_18.65_wing_buffer_50.70pts_OTM_narrowed_18.65_still_safe_PE_spread_intrinsic_49.30_widened_CE_249.30pts_OTM_safe_force_square_14_30_5min",
            "tight_side_watch": "PE_57300_wing_50.70pts_above_DANGEROUS_short_57400_PE_49.30pts_ITM_worsened_CE_57600_249.30pts_OTM_safe"
        }
    ],
    "executor_status": {
        "standalone_executor": "dead_3d_no_orders_since_2026-08-22",
        "in_process_resilient": "not_processing_brain_actions",
        "force_square_backstop": "14_30_IST_5min_away",
        "working_exit": "force_square_only"
    },
    "tick_summary_14_25": (
        "63rd tick of day, CONTINUE HOLD ALL. Bias=cautious. "
        "STATE CHANGE vs 14:20: BN WHIPSAWED -18.65pts in 5 min, back from 57369.35 to 57350.70 (AT 57350 trigger band). "
        "The 14:20 'recovery' was a 5-min overshoot, not sustained. "
        "NIFTY 24164.30 (essentially flat +1.25pts). 64.30 above 24100 PE (49.30 above 24115 trigger - safe). "
        "Short 24300 CE 135.70 OTM (NARROWED 1.25 - still very safe). Long 24400 CE 235.70 OTM (deep green). "
        "BN 57350.70 (AT trigger band, was 19.35 ABOVE at 14:20, NOW 0.70 ABOVE - effectively AT trigger). "
        "BN short 57400 PE 49.30 ITM (WORSENED 18.65 from 30.65 ITM). "
        "BN long 57300 PE wing buffer 50.70 OTM (NARROWED 18.65 from 69.35 - STILL OTM safe but DANGEROUS gamma zone). "
        "PE SPREAD INTRINSIC 49.30 of 100 (REWIDENED 18.65 from 30.65 - back in danger zone). "
        "Max loss only if BN<57250 (100.70pts below). "
        "CE side 249.30 OTM (NARROWED 18.65 - still safe). "
        "VIX 11.25-11.27 (flat low). "
        "UNREALIZED PNL est: NIFTY +1900 INR (flat). BN IC est PnL ~-1750 INR (WORSENED from -100, -1650 INR deterioration in 5 min). "
        "TOTAL est PnL: +150 INR [down from +1800 at 14:20, -1650 INR in 5 min]. "
        "The BN whipsaw cost -1650 INR in 5 min. "
        "REASON FOR HOLD (UNCHANGED): (1) Executor dead 3d, only force-square at 14:30 works - manual close via brain_actions.json is a no-op. "
        "(2) 5 min to 14:30 - force-square IMMINENT. "
        "(3) Even with BN whipsaw back to trigger, 5 min more hold vs immediate force-square is identical outcome. "
        "(4) NIFTY fully safe. "
        "(5) BN 57300 wing still 50.70 OTM (not breached). "
        "(6) Force-square at 14:30 closes both legs of both strategies at market. "
        "NEXT TICK TRIGGERS: BN<57250 = full max loss on PE accept; NIFTY<24115 = NIFTY IC PE in trouble accept; "
        "force-square at 14:30 closes both legs of both strategies."
    ),
    "timestamp": "2026-08-25T08:55:00Z",
    "confidence": 0.75,
    "risk_budget_pct": 0.0,
    "rationale": "HOLD ALL - 5 min to 14:30 force-square, executor dead 3d so manual close no-op. BN whipsawed -18.65pts back to 57350.70 trigger band (PE spread widened back to 49.30, wing buffer narrowed to 50.70 OTM). NIFTY safe. Force-square imminent is the only working exit. Let final 5 min pass and let force-square close positions."
}

# Read existing file to preserve history
with open(path, 'r', encoding='utf-8') as f:
    text = f.read()

# Find the last_decision block boundaries
# The block starts after "last_decision": and ends at the closing }
# Approach: use a regex to find the "history" key after last_decision
# Simpler: find "last_decision": and then find the matching closing brace at the
# same depth, then find where "history" starts.

# Find start
ld_start = text.find('"last_decision"')
print(f'last_decision starts at {ld_start}')

# Find "history" key (which is at depth 1, after last_decision)
hist_idx = text.find('"history"', ld_start)
print(f'history key at {hist_idx}')

# Walk back from hist_idx to find the closing "}," of last_decision
# The pattern is: "},\n  \"history\""
# Find the closing brace of last_decision
end_marker = '},\n  "history"'
end_idx = text.find(end_marker, ld_start)
print(f'end marker "}},"\\n  \\"history\\"" at {end_idx}')

if end_idx < 0:
    # Try without newline variations
    end_marker2 = '},\n"history"'
    end_idx = text.find(end_marker2, ld_start)
    print(f'try 2: end marker at {end_idx}')

# The last_decision block is from ld_start to end_idx+1 (inclusive of "}")
ld_end = end_idx + 1  # includes the closing "}"
print(f'last_decision block: {ld_start} to {ld_end}, length={ld_end - ld_start}')

# Also need to find the line preceding last_decision that contains "call_count_today"
# Update call_count_today from 61 to 62
cct_start = text.find('"call_count_today"')
cct_end = text.find(',', cct_start)
cct_line = text[cct_start:cct_end]
print(f'call_count_today line: {cct_line}')

# Replace call_count_today
new_cct_line = '"call_count_today": 62'
new_text = text[:cct_start] + new_cct_line + text[cct_end:]

# Now find the last_decision block in new_text
ld_start2 = new_text.find('"last_decision"')
hist_idx2 = new_text.find('"history"', ld_start2)
end_marker3 = '},\n  "history"'
end_idx2 = new_text.find(end_marker3, ld_start2)
ld_end2 = end_idx2 + 1

# Build the new last_decision JSON
new_ld_json = '"last_decision": ' + json.dumps(new_last_decision, ensure_ascii=False, indent=2)

# Wait - the last_decision has indent of 2 spaces inside, but in the file it's at 4-space indent
# Need to add 2 more spaces to each line
lines = new_ld_json.split('\n')
indented = [lines[0]] + ['  ' + ln for ln in lines[1:]]
new_ld_indented = '\n'.join(indented)

# Replace
rebuilt = new_text[:ld_start2] + new_ld_indented + '\n  ' + new_text[ld_end2:]

# Verify
try:
    parsed = json.loads(rebuilt)
    print('OK - JSON parses')
    print('today_date:', parsed['today_date'])
    print('call_count_today:', parsed['call_count_today'])
    print('last_bias:', parsed['last_decision']['bias'])
    print('last_actions:', parsed['last_decision']['actions'])
    print('last_ist_time:', parsed['last_decision']['ist_time'])
    print('history items:', len(parsed['history']))
    # Write back
    with open(path, 'w', encoding='utf-8') as f:
        f.write(rebuilt)
    print('Wrote file, size=', len(rebuilt))
except json.JSONDecodeError as e:
    print('STILL BROKEN:', e)
    pos = e.pos
    print('Context:', repr(rebuilt[max(0, pos - 60):pos + 60]))
