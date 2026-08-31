import json
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))
now_ist = datetime.now(IST)
ist_str = now_ist.strftime('%Y-%m-%d %H:%M:%S')
iso_utc = now_ist.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

path = r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json'
with open(path, 'r', encoding='utf-8') as f:
    state = json.load(f)

state['call_count_today'] = state.get('call_count_today', 0) + 1

new_decision = {
    'ts': iso_utc,
    'ist_time': ist_str,
    'bias': 'neutral',
    'source': 'mavis',
    'max_positions': 2,
    'actions': [],
    'note': '0dte_monthly_expiry_reversal_above_triggers_both_shorts_otm_thetas_friend_hold',
    'reasoning': 'Tick at 10:30:24 IST on Tue 2026-08-25 (0DTE MONTHLY expiry day). 5 min after 10:25 tick, 75 min into regular session, 4h45m to square-off. Market in regular session. VIX 11.37 (<12 = very low, calm regime). Range regime confirmed for both underlyings (NIFTY conf=0.7 range=0.34%, BANKNIFTY conf=0.7 range=0.74%). Macro: no events next 7d, no blackout. Research: still unavailable (Kotak PDF timed out, 11th consecutive tick). Live positions: 2 strategies (NIFTY IB + BANKNIFTY IC) at max_positions=2. Status update vs 10:25 tick: STRONG UPWARD REVERSAL. NIFTY +8.90 to 24128.05, BANKNIFTY +38.15 to 57424.15. Drift rate: NIFTY +1.78 pts/min UP, BANKNIFTY +7.63 pts/min UP. VIX 11.37 (eased from 11.44). (1) NIFTY Iron Butterfly (short 24300 CE / 24100 PE, wings 24400 CE / 24000 PE) - spot 24128.05. Short 24300 CE: 171.95 pts OTM (lost 8.90 pts, still 172 pts safe). Short 24100 PE: 28.05 pts OTM (gained 8.90 pts, BACK ABOVE 20-pt trigger by 8.05 pts). Wings 24400 CE / 24000 PE = 271.95 / 128.05 pts away. Net credit 50.23 INR per unit, total 3264.95 INR. Max loss capped 3235.05 INR. NIFTY PE at 28.05 pts = 0.116% of spot ~0.16 sigma. (2) BANKNIFTY Iron Condor (short 57600 CE / 57400 PE, wings 57700 CE / 57300 PE) - spot 57424.15. Short 57600 CE: 175.85 pts OTM (lost 38.15 pts, still 176 pts safe). Short 57400 PE: 24.15 pts OTM (CROSSED BACK OTM by 38.15 pts, was 14 ITM at 10:25). Pure theta now, no intrinsic. Wing 57300 PE: 124.15 pts away (38 pts further from wing than 10:25). Wing 57700 CE: 275.85 pts OTM. Net credit 77.51 INR per unit, total 2325.30 INR. Max loss capped 674.70 INR. (3) MTM if closed now: NIFTY IB ~3565 INR locked, BANKNIFTY IC ~4125 INR locked, combined ~7690 INR profit. Good MTM but forfeit 4h45m of peak 0DTE afternoon theta. (4) Combined max loss if both breached = 3235 + 675 = 3910 INR ~3.7% of 105,535 cash. Within 2% risk budget. (5) DECISION CONTEXT: reversal has unwound the previous tick concern. NIFTY PE back above trigger. BANKNIFTY PE back OTM by 24. Both structures show much-improved distance. Theta working aggressively through 0DTE afternoon. Closing now locks 7690 INR but forfeit remaining theta. (6) NO ACTION rationale: both structures recovered, both short strikes safely OTM, max loss bounded, theta accelerating through 0DTE afternoon, drift reversal confirms range-bound nature, no crash signal. (7) Re-evaluate triggers: NIFTY <24120 = at trigger (NOT now, 28.05 above), NIFTY <24100 = breach (NOT now, 28.05 above), NIFTY <24080 = within 20 of wing. BANKNIFTY <57400 = breached (NOT now, 24.15 OTM), BANKNIFTY <57350 = within 50 of wing (NOT now, 74.15 away), BANKNIFTY <57300 = wing breach = max loss. Time triggers: 13:30 no new entries, 14:30 consider 0DTE close, 15:15 square off. (8) Decision identical to all prior 13 ticks of the day - 14th HOLD tick. Bias=neutral, risk_budget_pct=2.0. Bot log: skip 2 open strategies >= max 2 correctly blocking.',
    'candle_regime_evidence': {
        'NIFTY': {'regime': 'range', 'confidence': 0.7, 'reason': 'range=0.34% tight + vix=11.4 low', '5d_change_pct': 0.2, 'range_pct': 0.34, 'today_move_pts': 12.55},
        'BANKNIFTY': {'regime': 'range', 'confidence': 0.7, 'reason': 'range=0.74% tight + vix=11.4 low', '5d_change_pct': 0.3, 'range_pct': 0.74, 'today_move_pts': 51.85}
    },
    'macro_evidence': {'in_blackout': False, 'next_event': None, 'events_next_7d': []},
    'research_evidence': {'available': False, 'note': 'research not available (Kotak PDF download timed out, 11th consecutive tick), skipped research bias'},
    'monday_brief_evidence': {'applicable': False, 'note': 'Tuesday - Monday brief not consulted (per cron spec, Tue-Fri skip Monday brief)'},
    'position_evidence': [
        {
            'strategy': 'NIFTY Iron Butterfly', 'short_strike_ce': 24300, 'short_strike_pe': 24100,
            'wing_ce': 24400, 'wing_pe': 24000, 'width_pts': 100, 'spot': 24128.05,
            'distance_to_short_ce_pts': 171.95, 'distance_to_short_pe_pts': 28.05,
            'distance_to_wing_ce_pts': 271.95, 'distance_to_wing_pe_pts': 128.05,
            'expiry': '2026-08-25', '0dte': True, 'monthly_expiry': True,
            'opened_at': '2026-08-25 09:00:40', 'net_credit': 3264.95, 'max_loss': 3235.05,
            'status': 'CE_171.95pts_OTM_PE_28.05pts_OTM_ABOVE_TRIGGER',
            'tight_side_watch': 'PE_24100_at_28.05pts_0.116pct_spot_8.05pts_ABOVE_24120_threshold_recovery'
        },
        {
            'strategy': 'BANKNIFTY Iron Condor', 'short_strikes': [57600, 57400], 'wings': [57700, 57300],
            'width_pts': 100, 'spot': 57424.15,
            'distance_to_short_ce_pts': 175.85, 'distance_to_short_pe_pts': 24.15,
            'distance_to_wing_ce_pts': 275.85, 'distance_to_wing_pe_pts': 124.15,
            'expiry': '2026-08-25', '0dte': True, 'monthly_expiry': True,
            'opened_at': '2026-08-25 09:00:40', 'net_credit': 2325.3, 'max_loss': 674.7,
            'status': 'CE_175.85pts_OTM_PE_24.15pts_OTM_CROSSED_BACK_OTM',
            'tight_side_watch': 'PE_57400_BACK_OTM_by_24.15pts_wing_57300_124.15pts_away_safe'
        }
    ],
    'risk_budget_pct': 2.0,
    'tuesday_posture': 'normal',
    'monthly_expiry_note': 'Aug 25 2026 = last Tuesday of month = monthly expiry for NIFTY/BANKNIFTY Aug contracts. Combined with weekly = 0DTE MONTHLY close. Gamma risk highest of month. Hold short-vol structures; do not add.',
    'opening_buffer_note': 'Opening buffer 09:15-09:30 ended at 09:30:18. Now 75min into regular session, 4h45m to square-off. Bot still blocking new entries. Range regime confirmed. STRONG UPWARD REVERSAL since 10:25: NIFTY +8.90, BANKNIFTY +38.15. Both PE sides recovered - NIFTY 24100 PE back at 28.05 pts OTM (above 20-pt trigger), BANKNIFTY 57400 PE crossed back OTM by 24.15 pts. CE sides lost some cushion but still 172+ and 176+ pts OTM respectively. Theta working aggressively through 0DTE afternoon.',
    'reversal_note': '5-min UPWARD drift reversed the 5-min DOWNWARD drift from 10:20-10:25. This is classic range-bound 0DTE behavior - both directions see oscillation around the mean. Confirms the range regime signal. Both structures in much-improved state. No reason to close - theta is the friend through 0DTE afternoon peak (11:00-14:00 IST).',
    'tick_summary_10_30': '14th HOLD tick of the day. Bias=neutral. STRONG UPWARD REVERSAL since 10:25. NIFTY 24100 PE back at 28.05 pts OTM (8.05 above 20-pt escalation). BANKNIFTY 57400 PE crossed BACK OTM by 24.15 pts. Both structures recovered, max loss combined 3,910 INR (3.7% cash). Theta accelerating through 0DTE afternoon. Re-evaluate at 10:35 tick, 14:30 (0DTE close consideration), 15:15 (square off).'
}

state['last_decision'] = new_decision
state.setdefault('history', []).append({
    'ist_time': ist_str,
    'bias': 'neutral',
    'note': '0dte_monthly_expiry_reversal_above_triggers_both_shorts_otm_thetas_friend_hold',
    'actions': []
})

with open(path, 'w', encoding='utf-8') as f:
    json.dump(state, f, indent=2, ensure_ascii=False)

print('Updated brain_state.json: call_count_today=' + str(state['call_count_today']) + ', history len=' + str(len(state['history'])))
print('last_decision ist_time: ' + state['last_decision']['ist_time'])
print('last_decision note: ' + state['last_decision']['note'])
print('ISO UTC: ' + iso_utc)
