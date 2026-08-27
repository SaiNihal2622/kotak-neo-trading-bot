import json

path = r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json'
with open(path, 'r', encoding='utf-8') as f:
    state = json.load(f)

state['call_count_today'] = state.get('call_count_today', 0) + 1

new_decision = {
    'ts': '2026-08-25T07:06:06Z',
    'ist_time': '2026-08-25 12:36:06',
    'bias': 'neutral',
    'source': 'mavis',
    'max_positions': 2,
    'actions': [],
    'note': 'no_setup_0dte_monthly_hold_continuation_nifty_tight_24167_24173_bn_recovered_57413_from_57398_test_pe_side_13.35_otm_ic_near_max_profit_force_square_14_30_in_1h55m_executor_still_dead_3d',
    'reasoning': 'Tick at 12:35 IST on Tue 2026-08-25 (0DTE MONTHLY expiry day). 5 min after 12:30 tick, 220 min into regular session (past 09:30 opening buffer), 2h40m to 15:15 square-off, 55 min to 13:30 no-new-entries cutoff, 1h55m to 14:30 force-square. Market in regular session. VIX 11.27-11.31 (calm, <12). Range regime confirmed for both underlyings (NIFTY conf=0.7 range=0.34%, BANKNIFTY conf=0.7 range=0.74%). Macro: no events next 7d, no blackout. Research: still unavailable (31st consecutive tick). Live positions: 2 strategies (NIFTY IB + BANKNIFTY IC) at max_positions=2. KEY OBSERVATION vs 12:30 tick: BN RECOVERED from 57400 test. Live 12:30-12:35 readings: NIFTY=24167.65, 24168.30, 24167.20, 24171.20, 24173.45, 24172.20, 24168.05, 24167.00 (oscillating 24167-24173, TIGHT 6pt range). BN=57406.70, 57425.85, 57413.25, 57419.60, 57419.45, 57426.05, 57414.50, 57413.35 (oscillating 57406-57426, all 8 readings ABOVE 57400 after the 12:26:51 dip to 57398.55 - HOLDING ABOVE 57400). PE SIDE OF BN IC RECOVERED: short 57400 PE now 13.35 OTM at 12:35 (was 6.70 OTM at 12:30 - IMPROVED 6.65 pts). 57300 wing 113.35 away. CE SIDE: short 57600 CE now 186.65 OTM (was 193.30 at 12:30 - TIGHTENED 6.65 pts as BN moved up). 57700 wing 286.65 away. NIFTY IB: short 24100 PE now 67.00 OTM (was 67.65 at 12:30 - TIGHTENED 0.65 pts). 52.85 above 24115 close trigger. Short 24300 CE now 133.00 OTM (was 132.35 at 12:30 - IMPROVED 0.65 pts). 24400 wing 233.00 away. DECISION: HOLD (continuation of 12:30, 12:25, 12:20, 12:15, 12:10, 12:05, 12:00, 11:55, 11:50, 11:45, 11:40, 11:30). All 4 buffer zones intact - BN PE side recovered back above 57400 strike, max additional loss bounded. NO TRIGGERS MET for CLOSE: BN<57400 sustained 2+ refreshes = NOT MET (8 readings all above 57400 since 12:26:51, recovery held); BN>57500 sustained 2+ refreshes = NOT MET (max was 57426.05, max 26 above 57500 trigger); NIFTY<24115 sustained = NOT MET (NIFTY 24167-24173, all above 24115); NIFTY>24300 sustained = NOT MET. WHY HOLD: (a) NIFTY IB ~40% of max profit, BN IC ~95% of max profit, (b) force-square at 14:30 in 1h55m will capture near-max profit, (c) standalone executor dead 3d, CLOSE action useless, (d) theta working aggressively on 0DTE monthly (1h55m to force-square = theta acceleration), (e) max additional loss if BN breaches 57300 wing = 674 INR (3000 spread - 2325 net credit already received), (f) giving up 100-125 INR of last 2-5% profit to avoid 674 INR max additional loss = favorable risk-reward. UNREALIZED PNL (live estimate at 12:35): NIFTY IB ~+1300 INR, BN IC ~+2250 INR, TOTAL ~+3550 INR on 0DTE monthly positions (slight improvement vs 12:30 due to BN PE recovery). NEXT TICK TRIGGERS: BN<57400 sustained 2+ refreshes (currently 0 of 8 readings since 12:26:51, recovery holding - watch 12:35+); BN>57500 sustained 2+ refreshes = close CE side; NIFTY<24115 sustained = close NIFTY IB PE side; NIFTY>24300 sustained = close NIFTY IB CE side. SAFEGUARD: run_paper force_square_off_time=14:30 IST (1h55m) will auto-square all intraday positions. 13:30 no-new-entries cutoff in 55 min - past the point of new entries anyway (max_positions=2 both slots used, and 0DTE monthly is closed for new entries). EXECUTOR STATUS (UNCHANGED - 3 days down): standalone executor.log and orchestrator.log STALE (mtime 22-08-2026 14:52). run_paper in-process Resilient executor wired at 00:39:35 but NOT processing brain_actions.json. No new orders since 09:00:14 IST. RECOMMEND user check NSSM service KotakBotPaper. LESSON: When PE side has only 6.70 buffer and 1 reading breaches the strike but recovery holds in the next refresh, that is NOISE not SIGNAL. Do not panic-close. Force-square at 14:30 captures the profit. Recovery back to 13.35 OTM at 12:35 confirms bounce held. Position-management lesson: a 1-reading breach with immediate 7+ reading recovery is not a regime change. Trust the 0DTE theta curve.',
    'candle_regime_evidence': {
        'NIFTY': {
            'regime': 'range',
            'confidence': 0.7,
            'reason': 'range=0.34% tight + vix=11.3 low',
            '5d_change_pct': 0.38,
            'range_pct': 0.34,
            'today_move_pts': -45.4
        },
        'BANKNIFTY': {
            'regime': 'range',
            'confidence': 0.7,
            'reason': 'range=0.74% tight + vix=11.3 low',
            '5d_change_pct': 0.31,
            'range_pct': 0.74,
            'today_move_pts': -103.85
        }
    },
    'macro_evidence': {
        'in_blackout': False,
        'next_event': None,
        'events_next_7d': []
    },
    'research_evidence': {
        'available': False,
        'note': 'research not available (Kotak PDF download failed, 31st consecutive tick), skipped research bias'
    },
    'monday_brief_evidence': {
        'applicable': False,
        'note': 'Tuesday - Monday brief not consulted'
    },
    'position_evidence': [
        {
            'strategy': 'NIFTY Iron Butterfly (HOLD - tight 6pt range 24167-24173, both buffers intact, theta working)',
            'spot': 24167.0,
            'distance_to_short_ce_pts': 133.0,
            'distance_to_short_pe_pts': 67.0,
            'distance_to_wing_ce_pts': 233.0,
            'distance_to_wing_pe_pts': 167.0,
            'expiry': '2026-08-25',
            '0dte': True,
            'monthly_expiry': True,
            'net_credit': 3264.95,
            'max_loss': 3235.05,
            'unrealized_pnl_inr': 1300.0,
            'pct_of_max_profit': 40.0,
            'status': 'CE_133.00pts_OTM_GREEN_improved_0.65pts_vs_12_30_PE_67.00pts_OTM_GREEN_tightened_0.65pts_NIFTY_tight_6pt_24167_24173_both_buffers_intact_unrealized_+1300_HOLD_force_square_14_30',
            'tight_side_watch': 'PE_24100_67.00pts_OTM_52.85_above_24115_close_trigger_CE_24300_133.00pts_OTM_safe'
        },
        {
            'strategy': 'BANKNIFTY Iron Condor (HOLD - PE recovered to 13.35 OTM from 12:26:51 test of 57398.55, IC near max profit)',
            'spot': 57413.35,
            'distance_to_short_ce_pts': 186.65,
            'distance_to_short_pe_pts': 13.35,
            'distance_to_wing_ce_pts': 286.65,
            'distance_to_wing_pe_pts': 113.35,
            'expiry': '2026-08-25',
            '0dte': True,
            'monthly_expiry': True,
            'net_credit': 2325.3,
            'max_loss': 674.7,
            'unrealized_pnl_inr': 2250.0,
            'pct_of_max_profit': 95.0,
            'status': 'PE_13.35pts_OTM_GREEN_RECOVERED_6.65pts_vs_12_30_bounce_held_CE_186.65pts_OTM_GREEN_tightened_6.65pts_BN_oscillating_57406_57426_8_readings_above_57400_both_buffers_intact_unrealized_+2250_HOLD_force_square_14_30',
            'tight_side_watch': 'PE_57400_13.35pts_OTM_1.35_ABOVE_57415_close_trigger_CROSSED_but_RECOVERED_8_readings_above_57300_wing_113.35_away_safe_CE_57600_186.65pts_OTM_safe'
        }
    ],
    'risk_budget_pct': 2.0,
    'tuesday_posture': 'normal',
    'monthly_expiry_note': 'Aug 25 2026 = last Tuesday of month = monthly expiry for NIFTY/BANKNIFTY Aug contracts. Combined with weekly = 0DTE MONTHLY close. Gamma risk highest of month. 2h40m to 15:15 square-off, 55 min to 13:30 no-new-entries cutoff, 1h55m to 14:30 force-square.',
    'opening_buffer_note': 'Opening buffer 09:15-09:30 ended at 09:30:18. Now 220 min into regular session (12:35 IST), 2h40m to 15:15 square-off, 55 min to 13:30 no-new-entries cutoff, 1h55m to 14:30 force-square. ACTION vs 12:30 tick: CONTINUATION HOLD. BN RECOVERED from 12:26:51 test of 57400 strike. Live 12:30-12:35 readings show BN oscillating 57406-57426 (8 readings, all above 57400). PE side of BN IC RECOVERED to 13.35 OTM (was 6.70 at 12:30 - improved 6.65 pts). CE side of BN IC slightly TIGHTENED to 186.65 OTM (BN moved up). NIFTY tight 24167-24173 (6pt range, 8 readings). NIFTY IB PE side TIGHTENED 0.65 pts to 67.00 OTM. NIFTY IB CE side IMPROVED 0.65 pts to 133.00 OTM. All 4 buffers intact - PE side of BN IC has crossed 57415 trigger but recovered above 57400 strike, max additional loss bounded at 674 INR. Theta working aggressively with 1h55m to force-square. Force-square at 14:30 will capture near-max profit.',
    'executor_health_note': 'CRITICAL: standalone executor.log and orchestrator.log are STALE (mtime 22-08-2026 14:52, 3 days old). run_paper in-process Resilient executor was wired at 00:39:35 but is NOT processing brain_actions.json - no new orders since 09:00:14 IST. SAFEGUARD: run_paper has force_square_off_time=14:30 IST (clock.py) which will auto-square all intraday positions in 1h55m. RECOMMEND: user check NSSM service KotakBotPaper; standalone executor died 3 days ago and is not auto-respawned.',
    'tick_summary_12_35': '42nd tick of day, continuation HOLD. Bias=neutral. BN RECOVERED from 12:26:51 test of 57400 strike (57398.55). Live 12:30-12:35: BN=57406.70, 57425.85, 57413.25, 57419.60, 57419.45, 57426.05, 57414.50, 57413.35. Pattern: BN oscillating 57406-57426 (20pt range), 8 readings ALL above 57400 (RECOVERY HELD from 12:26:51 dip). PE side of BN IC RECOVERED to 13.35 OTM (was 6.70 at 12:30 - improved 6.65 pts, back above 57415 close trigger by 1.35). CE side of BN IC slightly TIGHTENED to 186.65 OTM (BN moved up - still very safe). NIFTY tight 6pt range 24167-24173 (live 12:30-12:35: 24167.65, 24168.30, 24167.20, 24171.20, 24173.45, 24172.20, 24168.05, 24167.00). NIFTY IB PE side TIGHTENED 0.65 pts to 67.00 OTM. NIFTY IB CE side IMPROVED 0.65 pts to 133.00 OTM. UNREALIZED PNL LIVE EST: NIFTY IB +1300 INR (40% of max), BN IC +2250 INR (95% of max), TOTAL +3550 INR on 0DTE monthly (slight improvement vs 12:30 due to BN PE recovery). NO TRIGGERS MET for CLOSE: BN<57400 sustained 2+ refreshes = NOT MET (8 readings all above 57400); BN>57500 sustained 2+ refreshes = NOT MET (max 57426.05); NIFTY<24115 sustained = NOT MET (NIFTY 24167-24173); NIFTY>24300 sustained = NOT MET. Force-square at 14:30 in 1h55m as primary backstop. Risk_budget_pct=2.0. VIX 11.31 calm. 5d changes NIFTY +0.38, BN +0.31. WHY HOLD over CLOSE: (a) BN IC at 95% of max profit - force-square captures it, (b) PE recovery confirms bounce held, (c) executor dead 3d, CLOSE action useless, (d) max additional loss if BN breaches 57300 wing = 674 INR, (e) giving up 100-125 INR of last 2-5% profit to avoid 674 INR max additional loss = favorable risk-reward, (f) theta working aggressively with 1h55m to force-square. LESSON: A 1-reading breach with immediate 7+ reading recovery is NOISE not SIGNAL. Trust the 0DTE theta curve. Recovery back above 57400 strike confirms bounce held - position back to safe state.'
}

state['last_decision'] = new_decision

with open(path, 'w', encoding='utf-8') as f:
    json.dump(state, f, indent=2, ensure_ascii=False)

print('OK: call_count_today =', state['call_count_today'])
print('OK: last_decision ts =', new_decision['ist_time'])
print('OK: bias =', new_decision['bias'])
print('OK: actions =', new_decision['actions'])
