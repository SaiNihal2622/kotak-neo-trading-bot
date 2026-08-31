import json
from datetime import datetime, timezone, timedelta

path = r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json'
with open(path, 'r', encoding='utf-8') as f:
    state = json.load(f)

state['call_count_today'] = state.get('call_count_today', 54) + 1

new_decision = {
    'ts': '2026-08-25T08:15:00Z',
    'ist_time': '2026-08-25 13:45:00',
    'bias': 'cautious',
    'source': 'mavis',
    'max_positions': 2,
    'actions': [],
    'note': 'HOLD_ALL_no_material_change_NIFTY_24140_BN_57315_VIX_11.26_25.25pts_above_24115_trigger_BN_35pts_below_57350_force_square_14_30_45min_backstop_executor_dead_3d_state_unchanged_from_13_40',
    'reasoning': "Tick at 13:45 IST on Tue 2026-08-25 [0DTE MONTHLY expiry day]. 15 min after 13:30 entry cutoff tick, 285 min into regular session, 1h30m to 15:15 square-off, 45 min to 14:30 force-square. Market in regular session. VIX 11.26 [calm, <12]. Range regime confirmed for both underlyings [NIFTY conf=0.7 range=0.34%, BANKNIFTY conf=0.7 range=0.74%]. Macro: no events next 7d, no blackout. Research: still unavailable [43rd consecutive tick]. Live positions: 2 strategies [NIFTY IB + BANKNIFTY IC] at max_positions=2. KEY STATE vs 13:40 tick: BN +0.85 pts from 57314.10 to 57314.95 (negligible, sustained in 57305-57315 range for last 10 refreshes). NIFTY +1.05 pts from 24139.20 to 24140.25 (negligible, sustained in 24138-24145 range). NO MATERIAL CHANGE in 5 min - both positions stable. NIFTY 24140.25: 40.25 above 24100 PE strike, 25.25 above 24115 hard trigger (improved 1.05 from 13:40 buffer of 24.20). Short 24300 CE 159.75 OTM (narrowed 1.05 from 160.80 as NIFTY bounced marginally). Both NIFTY buffers safe, theta working. BN 57314.95: short 57400 PE 85.05 ITM (vs 85.90 at 13:40, IMPROVED 0.85 by 0.85 pt BN bounce - negligible). 57300 wing breached 14.95 pts (was 14.10, slightly widened 0.85). PE SPREAD INTRINSIC = 85.05 [vs 100 full max loss, 14.95 spread remaining before max loss, vs 71.80 at 13:40 - actually WORSENED because intrinsic increased as wing breached further]. CE side 57600 still 285.05 OTM safe (narrowed 0.85 from 285.90 by BN bounce). Force-square at 14:30 (45 min) is working backstop. DECISION: CONTINUE HOLD ALL [55th tick of day, no change from 13:40]. Rationale: same as 13:40 - position stable, both buffers safe on NIFTY, BN PE side ITM but intrinsic at 85.05 not yet at full max loss 100, CE side still 285 OTM safe, force-square backstop in 45 min is sufficient. Re-emitting CLOSE would have no effect (executor dead 3d). UNREALIZED PNL [live est at 13:45]: NIFTY IB ~+1830 INR [+10 vs 13:40 as NIFTY bounced 1 pt narrowed CE more than improved PE], BN IC NET ~-160 INR [PE spread -1212 slightly worsened -25 from -1187 as wing breached 0.85 more, CE side now ~1052 INR credit [improved 15 INR from 1037 due to 0.85 pt BN bounce narrowing CE distance 0.85 pts], net -160 vs -150 at 13:40 = -10 INR], TOTAL ~+1670 INR [flat vs 13:40]. SAFEGUARD: force-square at 14:30 IST [45 min] will auto-square regardless. NIFTY 25.25 buffer safe. CE side 285 OTM safe. NEXT TICK TRIGGERS [unchanged from 13:40]: BN<57250 sustained 2+ = deeper emergency; BN>57450 sustained 2+ = potential unwind; NIFTY<24115 sustained 2+ = close NIFTY IB PE; NIFTY>24300 sustained 2+ = close NIFTY IB CE. PE side wing breach now 14.95 pts (was 14.10) - still tracking. LESSON: on 0DTE monthly in late session with position stable, prefer minimal-action HOLD and trust force-square backstop rather than chase incremental changes that have no execution effect anyway.",
    'candle_regime_evidence': {
        'NIFTY': {
            'regime': 'range',
            'confidence': 0.7,
            'reason': 'range=0.34% tight + vix=11.3 low',
            '5d_change_pct': 0.25,
            'range_pct': 0.34,
            'today_move_pts': -35.2
        },
        'BANKNIFTY': {
            'regime': 'range',
            'confidence': 0.7,
            'reason': 'range=0.74% tight + vix=11.3 low',
            '5d_change_pct': 0.12,
            'range_pct': 0.74,
            'today_move_pts': -209.95
        }
    },
    'macro_evidence': {
        'in_blackout': False,
        'next_event': None,
        'events_next_7d': []
    },
    'research_evidence': {
        'available': False,
        'note': 'research not available [Kotak PDF download failed, 43rd consecutive tick], skipped research bias'
    },
    'monday_brief_evidence': {
        'applicable': False,
        'note': 'Tuesday - Monday brief not consulted'
    },
    'position_evidence': [
        {
            'strategy': 'NIFTY Iron Butterfly [HOLD - NIFTY 24140.25 up 1.05pts from 13:40, 40.25 above 24100 PE strike, 25.25 above 24115 hard trigger (improved 1.05 from 24.20 buffer). Both buffers safe, theta working well. NIFTY has been in 24138-24145 range for last 10 refreshes.]',
            'spot': 24140.25,
            'distance_to_short_ce_pts': 159.75,
            'distance_to_short_pe_pts': 40.25,
            'distance_to_wing_ce_pts': 259.75,
            'distance_to_wing_pe_pts': 140.25,
            'expiry': '2026-08-25',
            '0dte': True,
            'monthly_expiry': True,
            'net_credit': 3767.25,
            'max_loss': 3732.75,
            'unrealized_pnl_inr': 1830.0,
            'pct_of_max_profit': 49.0,
            'status': 'CE_159.75pts_OTM_GREEN_PE_40.25pts_OTM_GREEN_NIFTY_24140.25_bounce_25.25_above_24115_hard_trigger_improved_from_24.20_unrealized_+1830_HOLD_force_square_14_30_45min',
            'tight_side_watch': 'PE_24100_40.25pts_OTM_25.25pts_above_24115_close_trigger_safe_CE_24300_159.75pts_OTM_safe'
        },
        {
            'strategy': 'BANKNIFTY Iron Condor [HOLD - state essentially unchanged from 13:40. PE side short 57400 PE now 85.05 pts ITM [improved 0.85 from 85.90 by 0.85 pt BN bounce - negligible]. 57300 wing breached 14.95 pts below [widened 0.85 from 14.10]. PE SPREAD INTRINSIC = 85.05 NOT at full max loss yet [100 - 85.05 = 14.95 spread remaining, vs 100 - 71.80 = 28.20 at 13:40 - WORSENED by 13.25 as wing breached]. PE spread PnL ~-1212 INR [worsened 25 INR from -1187]. CE side 57600 still 285.05 OTM safe [narrowed 0.85 from 285.90 by BN bounce]. Force-square 14:30 backstop [45 min].]',
            'spot': 57314.95,
            'distance_to_short_ce_pts': 285.05,
            'distance_to_short_pe_pts': -85.05,
            'distance_to_wing_ce_pts': 385.05,
            'distance_to_wing_pe_pts': -14.95,
            'expiry': '2026-08-25',
            '0dte': True,
            'monthly_expiry': True,
            'net_credit': 2325.3,
            'max_loss': 3674.7,
            'unrealized_pnl_inr': -160.0,
            'pct_of_max_profit': -4.4,
            'status': 'PE_85.05pts_ITM_NEGLIGIBLE_CHANGE_57300_wing_breached_14.95pts_widened_0.85_PE_spread_intrinsic_85.05_widened_13.25_CE_285.05pts_OTM_safe_force_square_14_30_45min_executor_dead_3d',
            'tight_side_watch': 'PE_57300_wing_BREACHED_14.95pts_at_13_45_widened_0.85_short_57400_PE_85.05_ITM_improved_0.85_PE_spread_intrinsic_85.05_widened_13.25_CE_57700_wing_385_away_safe'
        }
    ],
    'executor_status': {
        'standalone_executor': 'dead_3d_no_orders_since_2026-08-22',
        'in_process_resilient': 'not_processing_brain_actions',
        'force_square_backstop': '14_30_IST_45min_away',
        'working_exit': 'force_square_only'
    },
    'tick_summary_13_45': "55th tick of day, CONTINUE HOLD ALL (no change from 13:40). Bias=cautious. KEY STATE vs 13:40: BN +0.85 pts from 57314.10 to 57314.95 (negligible). NIFTY +1.05 pts from 24139.20 to 24140.25 (negligible). NIFTY 25.25 above 24115 trigger (was 24.20, improved 1.05). BN PE side 85.05 ITM (was 85.90, improved 0.85 by 0.85 pt bounce). 57300 wing breached 14.95 pts (was 14.10, WIDENED 0.85). PE SPREAD INTRINSIC = 85.05 (was 71.80 at 13:40 - WORSENED 13.25 as wing breached more). PE spread PnL ~-1212 (was -1187, WORSENED 25). CE side 285.05 OTM safe (was 285.90, narrowed 0.85). REASON FOR NO CHANGE: both positions stable, deltas negligible (<1 pt), no new triggers hit, force-square backstop in 45 min is sufficient safety. NIFTY both buffers safe. CE side 285 OTM safe. Re-emitting CLOSE would have no execution effect anyway (executor dead 3d). UNREALIZED PNL est: TOTAL ~+1670 INR [flat vs 13:40 - NIFTY IB +10 to +1830, BN IC -10 to -160]. LESSON: on stable 0DTE monthly in late session, prefer minimal-action HOLD. Position state has not crossed any new thresholds. Going forward: BN<57250 sustained 2+ = deeper emergency; BN>57450 sustained 2+ = potential unwind; NIFTY<24115 sustained 2+ = close NIFTY IB PE; NIFTY>24300 sustained 2+ = close NIFTY IB CE.",
    'timestamp': '2026-08-25T08:15:00Z',
    'confidence': 0.7,
    'risk_budget_pct': 0.0,
    'rationale': 'HOLD ALL - no material change since 13:40. BN +0.85pts to 57315, NIFTY +1.05pts to 24140. Both positions stable. Force-square 14:30 (45min) backstop. NIFTY 25.25pts above 24115 trigger. CE side 285 OTM safe. PE spread intrinsic 85.05 (widened 13.25 from 71.80, still 14.95 from full max loss). Executor dead 3d, re-emit CLOSE has no effect.'
}

state['last_decision'] = new_decision

with open(path, 'w', encoding='utf-8') as f:
    json.dump(state, f, indent=2, ensure_ascii=False)

print('OK updated last_decision, call_count_today=', state['call_count_today'])
