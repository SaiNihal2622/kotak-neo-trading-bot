"""One-off tick updater for 14:20 IST brain_state.json."""
import json
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))
now_ist = datetime.now(IST)
ts_utc = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
ist_str = now_ist.strftime('%Y-%m-%d %H:%M:%S')

path = r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json'
with open(path, 'r', encoding='utf-8') as f:
    state = json.load(f)

state['call_count_today'] = state.get('call_count_today', 0) + 1

new_decision = {
  'ts': ts_utc,
  'ist_time': ist_str,
  'bias': 'cautious',
  'source': 'mavis',
  'max_positions': 2,
  'actions': [],
  'note': 'HOLD_ALL_NIFTY_24163.05_+9.5pts_from_14_15_63.05_above_24100_PE_IMPROVED_9.5_48.05_above_24115_trigger_IMPROVED_9.5_short_24300_CE_136.95_OTM_safe_NARROWED_9.5_BN_57369.35_+54.10pts_RECOVERED_19.35_ABOVE_57350_trigger_was_34.75_BELOW_short_57400_PE_30.65_ITM_was_84.75_IMPROVED_54.10_57300_PE_wing_buffer_69.35_OTM_was_15.25_DANGEROUS_NOW_SAFE_PE_spread_intrinsic_30.65_of_100_was_84.75_CE_57600_230.65_OTM_NARROWED_54.10_still_safe_10min_to_14:30_force_square_backstop_working_exit_executor_dead_3d_CE_theta_working_hold_to_force_square',
  'reasoning': 'Tick at 14:20 IST on Tue 2026-08-25 [0DTE MONTHLY expiry day]. 50 min after 13:30 entry cutoff, 380 min into regular session, 10 min to 14:30 force-square, 55 min to 15:15. VIX 11.21-11.25 [calm, <12, range-bound confirmed]. Range regime both underlyings [NIFTY conf=0.7 range=0.34%, BANKNIFTY conf=0.7 range=0.74%]. Macro: no events, no blackout. Research: still unavailable. Live positions: 2 strategies [NIFTY IC + BN IC, both 100pt wide]. KEY STATE vs 14:15 tick: BN RECOVERED 54.10pts in 5 min - from 57315.25 to 57369.35. NIFTY also up 9.5pts from 24153.55 to 24163.05. CRITICAL: BN at 57369.35 is NOW 19.35 ABOVE 57350 hard trigger (was 34.75 BELOW at 14:15 - cross back over). This is MAJOR improvement. BN short 57400 PE 30.65 ITM (was 84.75 ITM, IMPROVED 54.10 - now only 30.65 deep). BN long 57300 PE wing buffer 69.35 OTM (was 15.25 DANGEROUS at 14:15, NOW SAFE 69.35 OTM). PE SPREAD INTRINSIC = 30.65 (was 84.75, IMPROVED 54.10 - out of danger zone). Max loss would only be hit if BN < 57250, which is now 119pts below. CE side 57600 230.65 OTM (was 284.75, NARROWED 54.10 - still safe). Long 57700 CE 330.65 OTM (deep green). NIFTY at 24163.05: 63.05 above 24100 PE strike (IMPROVED 9.5 from 53.55). 48.05 above 24115 hard trigger (IMPROVED 9.5 from 38.55). Short 24300 CE 136.95 OTM (NARROWED 9.5 from 146.45 - still very safe). Long 24400 CE 236.95 OTM (deep green). Long 24000 PE 163.05 OTM (deep green). VIX 11.21-11.25 range (essentially flat). UNREALIZED PNL [live est at 14:20]: NIFTY IC est PnL ~+1900 INR (slight improvement from +1800 at 14:15). BN IC: PE spread IMPROVED 54.10pts at gamma heavy +1500 INR recovery. CE narrowed 54.10pts -250 INR offset. BN IC est PnL ~-100 INR (HUGE improvement from -1600 at 14:15, +1500 INR recovery). TOTAL est PnL: NIFTY +1900 + BN -100 = +1800 INR [up from +200 at 14:15, +1600 INR in 5 min]. DECISION: CONTINUE HOLD ALL [62nd tick of day, call_count_today=61]. Rationale: 1) Executor dead 3d, re-emitting CLOSE has no effect - only force-square at 14:30 works. 2) 10 min to 14:30 - force-square imminent. 3) Both positions now SAFE - NIFTY fully, BN recovered back above 57350 trigger. 4) PE spread intrinsic reduced from 84.75 to 30.65 - max loss risk massively reduced. 5) CE side still has time value working for us. 6) Closing now vs at force-square: minimal PnL difference since both positions are out of danger. 7) Force-square at 14:30 closes both legs of both strategies. NEXT TICK TRIGGERS: BN<57250 = full max loss on PE, accept; NIFTY<24115 = NIFTY IC PE in trouble, accept; force-square at 14:30 closes both legs of both strategies.',
  'candle_regime_evidence': {
    'NIFTY': {
      'regime': 'range',
      'confidence': 0.7,
      'reason': 'range=0.34% tight + vix=11.2 low',
      '5d_change_pct': 0.36,
      'range_pct': 0.34,
      'today_move_pts': -10.6
    },
    'BANKNIFTY': {
      'regime': 'range',
      'confidence': 0.7,
      'reason': 'range=0.74% tight + vix=11.2 low',
      '5d_change_pct': 0.24,
      'range_pct': 0.74,
      'today_move_pts': 25.2
    }
  },
  'macro_evidence': {
    'in_blackout': False,
    'next_event': None,
    'events_next_7d': []
  },
  'research_evidence': {
    'available': False,
    'note': 'research not available [Kotak PDF download failed, 50th consecutive tick], skipped research bias'
  },
  'monday_brief_evidence': {
    'applicable': False,
    'note': 'Tuesday - Monday brief not consulted'
  },
  'position_evidence': [
    {
      'strategy': 'NIFTY Iron Condor [HOLD - NIFTY 24163.05 +9.5pts from 14:15. 63.05 above 24100 PE strike (IMPROVED 9.5). 48.05 above 24115 hard trigger (IMPROVED 9.5). Short 24300 CE 136.95 OTM (NARROWED 9.5 - still very safe). Long 24400 CE 236.95 OTM (deep green). Long 24000 PE 163.05 OTM (deep green). All buffers safe, theta working well into close.]',
      'spot': 24163.05,
      'distance_to_short_ce_pts': 136.95,
      'distance_to_short_pe_pts': 63.05,
      'distance_to_wing_ce_pts': 236.95,
      'distance_to_wing_pe_pts': 163.05,
      'expiry': '2026-08-25',
      '0dte': True,
      'monthly_expiry': True,
      'net_credit': 3264.95,
      'max_loss': 3235.05,
      'unrealized_pnl_inr': 1900.0,
      'pct_of_max_profit': 58.7,
      'status': 'PE_63.05pts_OTM_safe_IMPROVED_9.5_48.05pts_above_24115_safe_IMPROVED_9.5_CE_136.95pts_OTM_safe_NARROWED_9.5_force_square_14_30_10min',
      'tight_side_watch': 'PE_24100_63.05pts_OTM_safe_IMPROVED_9.5_CE_24300_136.95pts_OTM_safe_NARROWED_9.5'
    },
    {
      'strategy': 'BANKNIFTY Iron Condor [HOLD - BN RECOVERED 54.10pts in 5 min. BN 57369.35 UP 54.10 from 57315.25. BN 19.35 ABOVE 57350 hard trigger (was 34.75 BELOW at 14:15, NOW BACK ABOVE). Short 57400 PE 30.65 ITM (was 84.75 ITM, IMPROVED 54.10). Long 57300 PE wing buffer 69.35 OTM (was 15.25 DANGEROUS, NOW SAFE 69.35 OTM). PE SPREAD INTRINSIC = 30.65 (was 84.75, IMPROVED 54.10 - out of danger zone). Max loss only if BN<57250. CE side 57600 230.65 OTM (NARROWED 54.10 - still safe). Long 57700 CE 330.65 OTM (deep green).]',
      'spot': 57369.35,
      'distance_to_short_ce_pts': 230.65,
      'distance_to_short_pe_pts': -30.65,
      'distance_to_wing_ce_pts': 330.65,
      'distance_to_wing_pe_pts': 69.35,
      'expiry': '2026-08-25',
      '0dte': True,
      'monthly_expiry': True,
      'net_credit': 2325.3,
      'max_loss': 1935.6,
      'unrealized_pnl_inr': -100.0,
      'pct_of_max_profit': -5.2,
      'status': 'BN_RECOVERED_57369.35_up_54.10pts_BACK_19.35pts_ABOVE_57350_trigger_PE_spread_30.65pts_ITM_improved_54.10_wing_buffer_69.35pts_OTM_safe_CE_230.65pts_OTM_NARROWED_54.10_still_safe_force_square_14_30_10min',
      'tight_side_watch': 'PE_57300_wing_69.35pts_above_SAFE_short_57400_PE_30.65pts_ITM_improved_54.10_CE_57600_230.65pts_OTM_safe'
    }
  ],
  'executor_status': {
    'standalone_executor': 'dead_3d_no_orders_since_2026-08-22',
    'in_process_resilient': 'not_processing_brain_actions',
    'force_square_backstop': '14_30_IST_10min_away',
    'working_exit': 'force_square_only'
  },
  'tick_summary_14_20': '62nd tick of day, CONTINUE HOLD ALL. Bias=cautious. STATE: BN RECOVERED 54.10pts in 5 min - back above 57350 trigger. NIFTY 24163.05 +9.5pts (63.05 above 24100 PE - IMPROVED 9.5, 48.05 above 24115 trigger - IMPROVED 9.5). BN 57369.35 +54.10pts (19.35 ABOVE 57350 trigger - was 34.75 BELOW, NOW BACK ABOVE). BN short 57400 PE 30.65 ITM (IMPROVED 54.10 from 84.75 ITM - now only 30.65 deep). BN long 57300 PE wing buffer 69.35 OTM (was 15.25 DANGEROUS, NOW SAFE 69.35 OTM). PE SPREAD INTRINSIC 30.65 (IMPROVED 54.10 from 84.75 - out of danger zone). Max loss only if BN<57250 (119pts below). CE side 230.65 OTM (NARROWED 54.10 - still safe). VIX 11.21-11.25 (flat). UNREALIZED PNL est: NIFTY +1900 INR (slight improvement from +1800). BN IC est PnL ~-100 INR (HUGE recovery from -1600, +1500 INR improvement in 5 min). TOTAL est PnL: +1800 INR [up from +200 at 14:15, +1600 INR recovery in 5 min]. PATTERN SHIFT: BN bounced from intraday low 57315.25 back to 57369.35 - the 14:15 DANGEROUS state was a 5-min overshoot, not a sustained breakdown. Both positions now SAFE. REASON FOR HOLD: 1) Executor dead 3d, only force-square works. 2) 10 min to 14:30 - force-square imminent. 3) Both positions SAFE now - PE spread at 30.65 intrinsic only, not max. 4) CE side has time value still working. 5) Closing now vs at force-square: minimal PnL difference. NEXT TICK TRIGGERS: BN<57250 = full max loss, accept; NIFTY<24115 = NIFTY IC PE in trouble, accept; force-square at 14:30 closes both legs of both strategies.',
  'timestamp': ts_utc,
  'confidence': 0.75,
  'risk_budget_pct': 0.0,
  'rationale': 'HOLD ALL - BN RECOVERED 54.10pts in 5 min, both positions now SAFE. NIFTY 63.05 above 24100 PE (IMPROVED 9.5), 48.05 above 24115 trigger (IMPROVED 9.5). BN 19.35 ABOVE 57350 trigger (was 34.75 BELOW - RECOVERED). BN short 57400 PE 30.65 ITM (IMPROVED 54.10). BN long 57300 PE 69.35 OTM (was 15.25 DANGEROUS, NOW SAFE). PE spread intrinsic 30.65 (was 84.75 - out of danger). 10 min to 14:30 force-square imminent. Executor dead 3d, only force-square works. Let theta work to force-square.'
}

state['last_decision'] = new_decision

if 'decisions' not in state:
    state['decisions'] = []

existing_times = [d.get('ist_time') for d in state.get('decisions', [])]
if ist_str not in existing_times:
    history_entry = {
        'ist_time': ist_str,
        'bias': 'cautious',
        'note': new_decision['note'],
        'actions': []
    }
    state['decisions'].insert(0, history_entry)

with open(path, 'w', encoding='utf-8') as f:
    json.dump(state, f, indent=2, ensure_ascii=False)

print('Updated brain_state.json: call_count_today=' + str(state['call_count_today']) + ', last_decision.ist_time=' + ist_str)
print('Decisions history: ' + str(len(state.get('decisions', []))) + ' entries')
