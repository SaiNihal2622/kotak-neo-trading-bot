"""Update brain_state.json: bump call_count, replace last_decision, preserve history."""
import json
import sys
from pathlib import Path

path = Path(r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json')

# Read with utf-8-sig to handle BOM if present
raw = path.read_text(encoding='utf-8-sig')
state = json.loads(raw)

# Bump call count
state['call_count_today'] = state.get('call_count_today', 0) + 1

# New last_decision
new_decision = {
    "ts": "2026-08-25T08:45:00Z",
    "ist_time": "2026-08-25 14:15:00",
    "bias": "cautious",
    "source": "mavis",
    "max_positions": 2,
    "actions": [],
    "note": "HOLD_ALL_NIFTY_24153.55_-1.75pts_53.55_above_24100_PE_NARROWED_1.75_38.55_above_24115_trigger_NARROWED_1.75_CE_side_146.45_OTM_safe_BN_57315.25_DOWN_24.55pts_DEEP_BELOW_57350_trigger_by_34.75pts_PE_spread_84.75_ITM_WORSENED_24.55_wing_buffer_15.25_DANGEROUS_NARROWED_24.55_CE_side_284.75_OTM_safe_15min_to_14:30_force_square_60min_to_15:15_executor_dead_3d_PE_spread_at_near_max_intrinsic_close_now_vs_force_square_same_PnL_CE_theta_working_sit_tight",
    "reasoning": "Tick at 14:15 IST on Tue 2026-08-25 [0DTE MONTHLY expiry day]. 45 min after 13:30 entry cutoff, 365 min into regular session, 15 min to 14:30 force-square, 60 min to 15:15. VIX 11.22 [calm, <12, range-bound confirmed]. Range regime both underlyings [NIFTY conf=0.7 range=0.34%, BANKNIFTY conf=0.7 range=0.74%]. Macro: no events, no blackout. Research: still unavailable. Live positions: 2 strategies [NIFTY IC + BN IC, both 100pt wide]. KEY STATE vs 14:10 tick: BN SLIPPED SIGNIFICANTLY 24.55pts in 5 min. Live spot at 14:15:14: NIFTY=24153.55 [DOWN 1.75 from 24155.30, essentially flat], BN=57315.25 [DOWN 24.55 from 57339.80, SIGNIFICANT SLIP]. VIX 11.22 (was 11.20, +0.02 - essentially flat). NIFTY 38.55 above 24115 hard trigger (was 40.30, NARROWED 1.75 - still safe). NIFTY 53.55 above 24100 PE strike (was 55.30, NARROWED 1.75 - still safe). NIFTY short 24300 CE 146.45 OTM (was 144.70, WIDENED 1.75 - safer). NIFTY long 24000 PE 153.55 OTM (deep green). NIFTY IC safe. BN at 57315.25: 34.75 BELOW 57350 trigger (was 10.20 below at 14:10, FURTHER 24.55pts BELOW - worst in day). BN short 57400 PE 84.75 ITM (was 60.20, WORSENED 24.55 by BN drop - deep ITM). BN long 57300 PE 15.25 OTM (was 39.80, NARROWED 24.55 - DANGEROUS, only 15.25pt wing buffer). PE SPREAD INTRINSIC = 84.75 (was 60.20, WORSENED 24.55 - near max 100). If BN drops 15 more pts to 57284, 57300 wing breached, PE spread at FULL MAX LOSS = 1936.5 INR. CE side 57600 284.75 OTM (was 260.20, WIDENED 24.55 - safer). Long 57700 CE 384.75 OTM (deep green). UNREALIZED PNL [live est at 14:15]: NIFTY IC est PnL ~+1800 INR (unchanged from 14:10, minor moves). BN IC: PE spread WIDENED 24.55pts at gamma-heavy -1100 INR additional loss, CE widened 24.55pts +300 INR offset. BN IC est PnL ~-1600 INR (down from -800 at 14:10, -800 deterioration). TOTAL est PnL: NIFTY +1800 + BN -1600 = +200 INR [down from +1000 at 14:10, -800 INR in 5 min]. LESSON from 14:10→14:15: BN STOPS OSCILLATING, NOW TRENDING DOWN SHARPLY. 14:00 overshoot to 57321.60 → 14:05 recovery to 57351.95 → 14:10 back to 57339.80 → 14:15 NOW 57315.25 (4 consecutive drops). Pattern: BN broke 57350 support, now testing next support at 57300 wing strike. If 57300 holds, position survives; if breached, max loss realized. The rate of drop suggests the 57300 wing may be tested within 5-10 min. DECISION: CONTINUE HOLD ALL [61st tick of day]. Rationale: 1) Executor dead 3d, re-emitting CLOSE has no effect - only force-square at 14:30 works. 2) 15 min to 14:30 - force-square imminent. 3) BN IC PE side at near-max intrinsic (84.75 of 100), closing now vs at force-square yields SAME PnL since both legs reach max value when BN < 57300. 4) CE side 284.75 OTM still has time value working for us. 5) NIFTY IC completely safe. 6) The only thing that saves the BN IC PE side is if BN bounces back above 57300+ in the next 15 min, which is possible given 0DTE monthly gamma but unlikely given the 5-min trend. NEXT TICK TRIGGERS: BN<57250 sustained = PE spread at full max loss + buffer lost, accept loss at 14:30; NIFTY<24115 sustained = NIFTY IC PE in trouble, accept loss at 14:30; force-square at 14:30 closes both legs of both strategies. URGENT WATCH: 57300 wing buffer 15.25pts - if BN holds above 57300 till 14:30, BN IC PE side may not realize full max loss.",
    "candle_regime_evidence": {
      "NIFTY": {
        "regime": "range",
        "confidence": 0.7,
        "reason": "range=0.34% tight + vix=11.2 low",
        "5d_change_pct": 0.32,
        "range_pct": 0.34,
        "today_move_pts": -10.6
      },
      "BANKNIFTY": {
        "regime": "range",
        "confidence": 0.7,
        "reason": "range=0.74% tight + vix=11.2 low",
        "5d_change_pct": 0.18,
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
      "note": "research not available [Kotak PDF download failed, 49th consecutive tick], skipped research bias"
    },
    "monday_brief_evidence": {
      "applicable": False,
      "note": "Tuesday - Monday brief not consulted"
    },
    "position_evidence": [
      {
        "strategy": "NIFTY Iron Condor [HOLD - NIFTY 24153.55 -1.75pts from 14:10. 53.55 above 24100 PE strike (NARROWED 1.75 - still safe). 38.55 above 24115 hard trigger (NARROWED 1.75 - still safe). Short 24300 CE 146.45 OTM (WIDENED 1.75 - safer). Long 24400 CE 246.45 OTM (deep green). Long 24000 PE 153.55 OTM (deep green). All buffers safe, theta working well into close.]",
        "spot": 24153.55,
        "distance_to_short_ce_pts": 146.45,
        "distance_to_short_pe_pts": 53.55,
        "distance_to_wing_ce_pts": 246.45,
        "distance_to_wing_pe_pts": 153.55,
        "expiry": "2026-08-25",
        "0dte": True,
        "monthly_expiry": True,
        "net_credit": 3264.95,
        "max_loss": 3235.05,
        "unrealized_pnl_inr": 1800.0,
        "pct_of_max_profit": 55.6,
        "status": "PE_53.55pts_OTM_safe_NARROWED_1.75_38.55pts_above_24115_safe_NARROWED_CE_146.45pts_OTM_safe_WIDENED_1.75_force_square_14_30_15min",
        "tight_side_watch": "PE_24100_53.55pts_OTM_safe_NARROWED_1.75_CE_24300_146.45pts_OTM_safe_WIDENED_1.75"
      },
      {
        "strategy": "BANKNIFTY Iron Condor [HOLD - BN SLIPPED 24.55pts in 5 min. BN 57315.25 DOWN 24.55 from 57339.80. BN 34.75 BELOW 57350 hard trigger (was 10.20 below at 14:10, FURTHER 24.55pts below). Short 57400 PE 84.75 ITM (was 60.20 ITM, WORSENED 24.55 - deep ITM). Long 57300 PE 15.25 OTM (was 39.80, NARROWED 24.55 - DANGEROUS, only 15.25pt wing buffer). PE SPREAD INTRINSIC = 84.75 (near max 100). If BN<57284 = full max loss. CE side 57600 284.75 OTM (WIDENED 24.55 - safer). Long 57700 CE 384.75 OTM (deep green).]",
        "spot": 57315.25,
        "distance_to_short_ce_pts": 284.75,
        "distance_to_short_pe_pts": -84.75,
        "distance_to_wing_ce_pts": 384.75,
        "distance_to_wing_pe_pts": 15.25,
        "expiry": "2026-08-25",
        "0dte": True,
        "monthly_expiry": True,
        "net_credit": 2325.3,
        "max_loss": 1935.6,
        "unrealized_pnl_inr": -1600.0,
        "pct_of_max_profit": -82.6,
        "status": "BN_SLIPPED_57315.25_down_24.55pts_DEEP_34.75pts_BELOW_57350_PE_spread_84.75pts_ITM_widened_24.55_wing_buffer_15.25pts_NARROWED_DANGEROUS_CE_284.75pts_OTM_WIDENED_24.55_force_square_14_30_15min",
        "tight_side_watch": "PE_57300_wing_15.25pts_above_DANGEROUS_NARROWED_24.55_short_57400_PE_84.75pts_ITM_widened_24.55_CE_57600_284.75pts_OTM_safe"
      }
    ],
    "executor_status": {
      "standalone_executor": "dead_3d_no_orders_since_2026-08-22",
      "in_process_resilient": "not_processing_brain_actions",
      "force_square_backstop": "14_30_IST_15min_away",
      "working_exit": "force_square_only"
    },
    "tick_summary_14_15": "61st tick of day, CONTINUE HOLD ALL. Bias=cautious. STATE: BN SLIPPED 24.55pts in 5 min. NIFTY 24153.55 -1.75pts (essentially flat, 38.55 above 24115 trigger - NARROWED 1.75 but still safe). BN 57315.25 -24.55pts (34.75 below 57350 trigger, slipped from 10.20 below to 34.75 below). BN short 57400 PE 84.75 ITM (WORSENED 24.55 from 60.20 - deep ITM). BN long 57300 PE wing buffer 15.25pts (NARROWED 24.55 from 39.80 - DANGEROUS). PE SPREAD INTRINSIC 84.75 (WORSENED 24.55 - near max 100). If BN<57284 = full max loss. CE side 284.75 OTM (WIDENED 24.55 - safer). VIX 11.22 (essentially flat). UNREALIZED PNL est: NIFTY +1800 INR (unchanged). BN IC est PnL ~-1600 INR (PE widened 24.55 at gamma -1100 additional, CE widened 24.55 +300 offset). TOTAL est PnL: +200 INR [down from +1000 at 14:10, -800 INR in 5 min]. PATTERN SHIFT: BN stops oscillating, now trending down sharply. 4 consecutive drops: 57321.60 → 57351.95 → 57339.80 → 57315.25. Next test is 57300 wing strike. 15 min to 14:30 force-square imminent. REASON FOR HOLD: 1) Executor dead 3d, only force-square works. 2) 15 min to 14:30 - force-square imminent. 3) PE side at near-max intrinsic (84.75 of 100), closing now vs at force-square yields same PnL since both legs at max value when BN<57300. 4) CE side still has time value working. 5) NIFTY safe. NEXT TICK TRIGGERS: BN<57250 = full max loss, accept; NIFTY<24115 = NIFTY IC PE in trouble, accept; force-square at 14:30 closes both legs of both strategies.",
    "timestamp": "2026-08-25T08:45:00Z",
    "confidence": 0.7,
    "risk_budget_pct": 0.0,
    "rationale": "HOLD ALL - BN SLIPPED 24.55pts in 5 min. NIFTY 38.55 above 24115 trigger (NARROWED 1.75 - still safe). BN 34.75 BELOW 57350 trigger. BN short 57400 PE 84.75 ITM (WORSENED 24.55 - deep ITM). BN long 57300 PE 15.25 OTM (NARROWED 24.55 - DANGEROUS, only 15.25pt wing buffer). PE spread intrinsic 84.75 (near max 100). If BN<57284 = full max loss. 15 min to 14:30 force-square imminent. Executor dead 3d, only force-square works. PE at near-max intrinsic - closing now vs at force-square same PnL. Hold for backstop."
}

state['last_decision'] = new_decision

# Write back WITHOUT BOM — send_trader_tg.py uses utf-8 not utf-8-sig
path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding='utf-8')
print(f"OK: brain_state.json updated. call_count_today={state['call_count_today']}")
