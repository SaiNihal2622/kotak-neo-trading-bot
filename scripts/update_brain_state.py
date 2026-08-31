"""Update brain_state.json: replace last_decision and append to history."""
import json
import sys

state_path = r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json"

with open(state_path, "r", encoding="utf-8") as f:
    state = json.load(f)

new_decision = {
    "ts": "2026-08-25T08:20:00Z",
    "ist_time": "2026-08-25 13:50:00",
    "bias": "cautious",
    "source": "mavis",
    "max_positions": 2,
    "actions": [],
    "note": "HOLD_ALL_PE_SPREAD_LOCKED_AT_FULL_MAX_LOSS_NIFTY_24133_BN_57293_VIX_11.33_18.5pts_above_24115_trigger_BN_56.3pts_below_57350_PE_intrinsic_100_locked_57300_wing_6.3pts_force_square_14_30_40min_backstop_CE_306_OTM_safe_executor_dead_3d_state_worsened_from_13_45",
    "reasoning": "Tick at 13:50 IST on Tue 2026-08-25 [0DTE MONTHLY expiry day]. 20 min after 13:30 entry cutoff tick, 290 min into regular session, 1h25m to 15:15 square-off, 40 min to 14:30 force-square. Market in regular session. VIX 11.33 [calm, <12]. Range regime confirmed for both underlyings [NIFTY conf=0.7 range=0.34%, BANKNIFTY conf=0.7 range=0.74%]. Macro: no events next 7d, no blackout. Research: still unavailable [44th consecutive tick]. Live positions: 2 strategies [NIFTY IB + BANKNIFTY IC] at max_positions=2. KEY STATE vs 13:45 tick: BN -21.25 pts from 57314.95 to 57293.70 (FASTER move than recent ticks, was <1pt/5min, now 4.25pt/min). NIFTY -6.75 pts from 24140.25 to 24133.50. VIX +0.07 from 11.26 to 11.33. NIFTY 24133.50: 33.50 above 24100 PE strike, 18.50 above 24115 hard trigger (NARROWED 6.75 from 25.25). Short 24300 CE 166.50 OTM (widened 6.75 from 159.75 as NIFTY dropped). Both NIFTY buffers safe, theta working well. BN 57293.70: short 57400 PE 106.30 ITM (WORSENED 21.25 from 85.05). 57300 wing breached 6.30 pts below (WORSENED 8.65 from 14.95 above). PE SPREAD INTRINSIC = 100 = FULL MAX LOSS [short 57400 PE 106.30 ITM - long 57300 PE 6.30 ITM = 100 spread]. This is the FIRST time the PE spread has hit max loss intraday. Once locked at 100, it cannot lose more even if BN drops further (1:1 gamma offset of long 57300 PE). CE side 57600 306.30 OTM safe (widened 21.25 from 285.05 by BN drop, more comfortable). Force-square at 14:30 (40 min) is working backstop. UNREALIZED PNL [live est at 13:50]: NIFTY IB ~+1830 INR [flat vs 13:45 as NIFTY drop 6.75 pts - CE narrowed 6.75 widening gain, PE widened 6.75 narrowing gain, net flat]. BN IC NET ~-1300 INR [PE spread locked at 100 max loss = -3000 INR on PE side vs credit +2325 absorbed, so PE side -675 INR. CE side improved 21 pts * 30 = +630 INR. Net BN IC ~-45 to -1300 INR range]. TOTAL ~+500 INR [down ~1170 from +1670 at 13:45]. LESSON: BN accelerated move in last 5 min locked the PE spread at max loss. The good news: PE spread is now gamma-locked at max loss (1:1 offset between short 57400 and long 57300). CE side benefited from BN drop (306 OTM now vs 285). Force-square at 14:30 will close both. DECISION: CONTINUE HOLD ALL [56th tick of day]. Rationale: PE spread locked at max loss cannot lose more, CE side 306 OTM safe (more room than before), NIFTY buffer 18.50 above 24115 trigger (still safe), force-square backstop 40 min is the only working exit (executor dead 3d), re-emitting CLOSE has no effect. Risk asymmetry: PE side is bounded, CE side has more room now. LESSON: when PE spread intrinsic hits max loss on 0DTE monthly, the position becomes a function of the CE side only — the PE side is locked. Focus on CE side distance.",
    "candle_regime_evidence": {
        "NIFTY": {
            "regime": "range",
            "confidence": 0.7,
            "reason": "range=0.34% tight + vix=11.3 low",
            "5d_change_pct": 0.25,
            "range_pct": 0.34,
            "today_move_pts": -42.0
        },
        "BANKNIFTY": {
            "regime": "range",
            "confidence": 0.7,
            "reason": "range=0.74% tight + vix=11.3 low",
            "5d_change_pct": 0.12,
            "range_pct": 0.74,
            "today_move_pts": -231.2
        }
    },
    "macro_evidence": {
        "in_blackout": False,
        "next_event": None,
        "events_next_7d": []
    },
    "research_evidence": {
        "available": False,
        "note": "research not available [Kotak PDF download failed, 44th consecutive tick], skipped research bias"
    },
    "monday_brief_evidence": {
        "applicable": False,
        "note": "Tuesday - Monday brief not consulted"
    },
    "position_evidence": [
        {
            "strategy": "NIFTY Iron Butterfly [HOLD - NIFTY 24133.50 down 6.75pts from 13:45, 33.50 above 24100 PE strike, 18.50 above 24115 hard trigger (NARROWED 6.75 from 25.25 buffer - getting closer but still safe). Both buffers safe, theta working. NIFTY 24300 CE 166.50 OTM (widened 6.75 from 159.75 as NIFTY dropped).]",
            "spot": 24133.50,
            "distance_to_short_ce_pts": 166.50,
            "distance_to_short_pe_pts": 33.50,
            "distance_to_wing_ce_pts": 266.50,
            "distance_to_wing_pe_pts": 133.50,
            "expiry": "2026-08-25",
            "0dte": True,
            "monthly_expiry": True,
            "net_credit": 3767.25,
            "max_loss": 3732.75,
            "unrealized_pnl_inr": 1830.0,
            "pct_of_max_profit": 49.0,
            "status": "CE_166.50pts_OTM_GREEN_PE_33.50pts_OTM_GREEN_NIFTY_24133.50_dropped_6.75pts_18.5pts_above_24115_hard_trigger_NARROWED_from_25.25_unrealized_+1830_HOLD_force_square_14_30_40min",
            "tight_side_watch": "PE_24100_33.50pts_OTM_18.50pts_above_24115_close_trigger_still_safe_CE_24300_166.50pts_OTM_safe_widened"
        },
        {
            "strategy": "BANKNIFTY Iron Condor [HOLD - PE spread LOCKED at full max loss. Short 57400 PE now 106.30 pts ITM [WORSENED 21.25 from 85.05 by 21.25 pt BN drop]. 57300 wing breached 6.30 pts below [WORSENED 8.65 from 14.95 above]. PE SPREAD INTRINSIC = 100 = FULL MAX LOSS [106.30 - 6.30 = 100]. Locked at max loss - cannot lose more even if BN drops further (1:1 gamma offset of long 57300 PE). CE side 57600 306.30 OTM safe [WIDENED 21.25 from 285.05 by BN drop - MORE comfortable than before]. Force-square 14:30 backstop [40 min].]",
            "spot": 57293.70,
            "distance_to_short_ce_pts": 306.30,
            "distance_to_short_pe_pts": -106.30,
            "distance_to_wing_ce_pts": 406.30,
            "distance_to_wing_pe_pts": -6.30,
            "expiry": "2026-08-25",
            "0dte": True,
            "monthly_expiry": True,
            "net_credit": 2325.3,
            "max_loss": 3674.7,
            "unrealized_pnl_inr": -1300.0,
            "pct_of_max_profit": -35.4,
            "status": "PE_SPREAD_LOCKED_AT_FULL_MAX_LOSS_100_intrinsic_short_57400_106.30_ITM_long_57300_6.30_ITM_57300_wing_BREACHED_6.30pts_WORSENED_8.65_CE_306.30pts_OTM_safe_WIDENED_21.25_force_square_14_30_40min_executor_dead_3d",
            "tight_side_watch": "PE_57300_wing_BREACHED_6.30pts_at_13_50_widened_8.65_short_57400_PE_106.30_ITM_worsened_21.25_PE_SPREAD_LOCKED_AT_MAX_LOSS_CE_57700_wing_406.30_away_safe_widened"
        }
    ],
    "executor_status": {
        "standalone_executor": "dead_3d_no_orders_since_2026-08-22",
        "in_process_resilient": "not_processing_brain_actions",
        "force_square_backstop": "14_30_IST_40min_away",
        "working_exit": "force_square_only"
    },
    "tick_summary_13_50": "56th tick of day, CONTINUE HOLD ALL. Bias=cautious. KEY STATE vs 13:45: BN -21.25pts from 57314.95 to 57293.70 (FASTER 4.25pt/min vs <1pt/5min). NIFTY -6.75pts from 24140.25 to 24133.50. NIFTY 18.50 above 24115 trigger (was 25.25, narrowed 6.75 - still safe). BN PE SPREAD LOCKED AT FULL MAX LOSS 100 (was 85.05, WIDENED 14.95). 57300 wing breached 6.30 pts (was 14.95 above, WIDENED 8.65). CE side 306.30 OTM safe (WIDENED 21.25 by BN drop - more comfortable). KEY INSIGHT: Once PE spread hits 100 max loss, it cannot lose more (1:1 gamma offset of long 57300 PE). Position risk is now CE-side-only. REASON FOR NO CHANGE: PE spread locked, CE side 306 OTM safe, NIFTY buffer 18.5 still safe, force-square 40 min backstop is only working exit. UNREALIZED PNL est: TOTAL ~+500 INR [down from +1670 at 13:45 by ~1170 INR - NIFTY IB flat at +1830, BN IC -1300 (PE spread locked -3000, CE side improved +630, net ~-1300 vs -160 at 13:45)]. LESSON: on 0DTE monthly, once PE spread hits max loss, the position is no longer at risk on PE side. Focus on CE side distance to gauge residual risk. NEXT TICK TRIGGERS: BN<57250 sustained 2+ = deeper emergency but PE already locked; BN>57450 sustained 2+ = potential unwind but PE locked so just close CE side; NIFTY<24115 sustained 2+ = close NIFTY IB PE; NIFTY>24300 sustained 2+ = close NIFTY IB CE.",
    "timestamp": "2026-08-25T08:20:00Z",
    "confidence": 0.7,
    "risk_budget_pct": 0.0,
    "rationale": "HOLD ALL - PE spread locked at full max loss 100 (cannot lose more), CE side 306 OTM safe (widened by BN drop), NIFTY buffer 18.5 still safe above 24115 trigger. Force-square 14:30 (40min) is only working exit. BN -21.25pts accelerated but PE side gamma-locked."
}

# Replace last_decision
state["last_decision"] = new_decision
state["call_count_today"] = 56

# Append to history
history_entry = {
    "ist_time": "2026-08-25 13:50:00",
    "bias": "cautious",
    "note": "0dte_monthly_hold_PE_SPREAD_LOCKED_AT_FULL_MAX_LOSS_100_BN_57293.70_down_21.25pts_NIFTY_24133.50_down_6.75pts_NIFTY_buffer_18.5pts_above_24115_CE_57600_306.30pts_OTM_safe_force_square_14_30_40min_backstop_executor_dead_3d_PE_gamma_locked_cannot_lose_more",
    "actions": []
}
state["history"].append(history_entry)

with open(state_path, "w", encoding="utf-8") as f:
    json.dump(state, f, indent=2, ensure_ascii=False)

print(f"OK - last_decision updated, history appended, call_count_today=56")
print(f"last_decision.ist_time: {state['last_decision']['ist_time']}")
print(f"history length: {len(state['history'])}")
print(f"last history entry: {state['history'][-1]['ist_time']} - {state['history'][-1]['note'][:80]}")
