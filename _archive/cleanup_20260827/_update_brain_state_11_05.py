# -*- coding: utf-8 -*-
import json
from datetime import datetime, timezone, timedelta

path = r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json'
with open(path, 'r', encoding='utf-8-sig') as f:
    state = json.load(f)

ist = timezone(timedelta(hours=5, minutes=30))
now_ist = datetime.now(ist)
ts_utc = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
ist_time = now_ist.strftime('%Y-%m-%d %H:%M:%S')

# En-dashes for tick direction markers (safe ASCII), keep em-dash outside keys
new_decision = {
    'ts': ts_utc,
    'ist_time': ist_time,
    'bias': 'neutral',
    'source': 'mavis',
    'max_positions': 2,
    'actions': [],
    'note': '0dte_monthly_expiry_sustained_drift_nifty_24139_bn_57444_pe_buffers_tightening_nifty_24.15_above_24115_bn_28.60_above_57415_ce_deescalated_bn_57600_156.40_otm_hold',
    'reasoning': (
        'Tick at 11:05 IST on Tue 2026-08-25 (0DTE MONTHLY expiry day). 5 min after 11:00 tick, '
        '110 min into regular session (past 09:30 opening buffer), 4h10m to 15:15 square-off, '
        '2h25m to 13:30 no-new-entries cutoff. Market in regular session. VIX 11.43 (flat from 11.47 at 11:00, '
        '-0.04; still <12 = very low, calm regime, theta friendly). Range regime confirmed for both underlyings '
        '(NIFTY conf=0.7 range=0.34%, BANKNIFTY conf=0.7 range=0.74%, both unchanged). '
        'Macro: no events next 7d, no blackout (in_blackout=false). Research: still unavailable '
        '(Kotak PDF timed out, 18th consecutive tick — skip research bias). Live positions: 2 strategies '
        '(NIFTY IB + BANKNIFTY IC) at max_positions=2. STATUS UPDATE vs 11:00 tick: SUSTAINED DOWNWARD DRIFT, '
        'NOT SPIKE-AND-REJECTION. LiveIndia refreshes since 11:00: 11:03:40 NF=24141.80 BN=57458.45 VIX=11.45, '
        '11:04:11 NF=24140.00 BN=57455.55 VIX=11.44, 11:04:41 NF=24141.25 BN=57453.80 VIX=11.44, '
        '11:05:12 NF=24139.15 BN=57443.60 VIX=11.43. BANKNIFTY DRIFTED -51.10 PTS from 11:00 '
        '(57494.70 -> 57443.60, -0.89% / 0.89 sigma, sustained over 3+ consecutive refreshes all below 57460). '
        'NIFTY DRIFTED -6.05 PTS from 11:00 (24145.20 -> 24139.15, -0.07 sigma). BANKNIFTY total move from '
        '10:55 spike (57573.50) to now (57443.60) = -129.90 PTS in 10 min. '
        '(1) NIFTY Iron Butterfly (short 24300 CE / 24100 PE, wings 24400 CE / 24000 PE) - spot 24139.15. '
        'Short 24300 CE: 160.85 pts OTM (GAINED 6.05 pts vs 11:00 154.80, further GREEN safe, 0.67% of spot). '
        'Short 24100 PE: 39.15 pts OTM (LOST 6.05 pts vs 11:00 45.20, now INSIDE YELLOW zone, '
        '24.15 above 24115 PE close trigger, 19.15 above 24120 escalation trigger). '
        'Wings 24400 CE / 24000 PE = 260.85 / 139.15 pts away. Net credit 50.23 INR per unit, total 3264.95 INR. '
        'Max loss capped 3235.05 INR. PE-side buffer reduced by 6 pts but still 24.15 above close trigger. '
        '(2) BANKNIFTY Iron Condor (short 57600 CE / 57400 PE, wings 57700 CE / 57300 PE) - spot 57443.60. '
        'Short 57600 CE: 156.40 pts OTM (GAINED 51.10 pts vs 11:00 105.30, MAJOR DE-ESCALATION, '
        '0.27% of spot, well GREEN safe). Short 57400 PE: 43.60 pts OTM (LOST 51.10 pts vs 11:00 94.70, '
        'now INSIDE YELLOW zone, 28.60 above 57415 PE close trigger, 23.60 above 57420 escalation trigger). '
        'Wings 57700 CE / 57300 PE = 256.40 / 143.60 pts away. Net credit 77.51 INR per unit, total 2325.30 INR. '
        'Max loss capped 674.70 INR. PE-side buffer reduced by 51 pts but still 28.60 above close trigger. '
        '(3) MTM if closed now: PE side tightened but BOTH CE sides have IMPROVED substantially. '
        'BANKNIFTY 57600 CE went from DEEP YELLOW to GREEN. Net theta acceleration favors holding. '
        '(4) Combined max loss if both breached = 3235 + 675 = 3910 INR ~3.7% of 105,535 cash. '
        '(5) DECISION CONTEXT: SUSTAINED 3-refresh downward drift in BANKNIFTY. Not spike-and-rejection — '
        'this is gradual, persistent. Total BANKNIFTY move -129.90 pts in 10 min is meaningful but not catastrophic. '
        'Today intraday range for BN = 57231.25 to 57653.85 (422 pts). Current 57443.60 is at 50th percentile '
        '(midpoint of today range). NIFTY intraday range = 24115.45 to 24198.25 (83 pts). '
        'Current 24139.15 is at 29th percentile (lower portion but not extreme). Both spots within reasonable '
        'range bounds. PE close triggers 57415/24115 intact. '
        '(6) ESCALATION RULES check: PE-side CLOSE: if BANKNIFTY<57415 (currently 28.60 above, safe) or '
        'NIFTY<24115 (currently 24.15 above, safe) -> NOT TRIGGERED. CE-side YELLOW zone: '
        'NIFTY in 24250-24300 OR BANKNIFTY in 57550-57600 -> NOT triggered (NIFTY 110.85 below 24250, '
        'BN 106.40 below 57550). CE-side RED: NIFTY>24300 OR BANKNIFTY>57600 -> NOT triggered. '
        'HARD TRIGGER 57580: BN is 136.40 below (was 85.30 at 11:00). '
        '(7) NO ACTION rationale: PE close triggers 24-29 pts away, both spots within intraday range midpoints, '
        'range regime confirmed, 0DTE theta still working for us (CE side massively de-escalated), '
        'max loss capped 3910 INR acceptable for 0DTE monthly, VIX flat at 11.43, no macro events. '
        'NEW WATCH: if BANKNIFTY<57430 (13.60 below current, inside sustained-pullback territory) '
        'for 2+ consecutive refreshes, consider pre-emptive PE-side close. '
        '(8) Time triggers: 13:30 no new entries (2h25m), 14:30 consider 0DTE close (3h25m), '
        '15:15 square off (4h10m). (9) Bias=neutral, risk_budget_pct=2.0. '
        '(10) Bot log: skip 2 open strategies >= max 2 correctly blocking. Tick count 88012 (11:04:43). '
        '(11) SUMMARY: 21st HOLD tick. Sustained downward drift but NOT breached. PE buffers tightened '
        '(NIFTY 24.15, BN 28.60 above close triggers) but still meaningful. CE side massively de-escalated '
        '(BN 57600 now 156.40 OTM). Range regime intact, 0DTE monthly expiry theta accelerating. '
        'HOLD with PE close triggers at 57415/24115 unchanged. '
        'NEW sustained-pullback watch: if BN<57430 for 2+ refreshes, pre-emptive PE close.'
    ),
    'candle_regime_evidence': {
        'NIFTY': {
            'regime': 'range',
            'confidence': 0.7,
            'reason': 'range=0.34% tight + vix=11.4 low',
            '5d_change_pct': 0.25,
            'range_pct': 0.34,
            'today_move_pts': -36.6
        },
        'BANKNIFTY': {
            'regime': 'range',
            'confidence': 0.7,
            'reason': 'range=0.74% tight + vix=11.4 low',
            '5d_change_pct': 0.35,
            'range_pct': 0.74,
            'today_move_pts': 82.9
        }
    },
    'macro_evidence': {
        'in_blackout': False,
        'next_event': None,
        'events_next_7d': []
    },
    'research_evidence': {
        'available': False,
        'note': 'research not available (Kotak PDF download timed out, 18th consecutive tick), skipped research bias'
    },
    'monday_brief_evidence': {
        'applicable': False,
        'note': 'Tuesday - Monday brief not consulted (per cron spec, Tue-Fri skip Monday brief)'
    },
    'position_evidence': [
        {
            'strategy': 'NIFTY Iron Butterfly',
            'short_strike_ce': 24300,
            'short_strike_pe': 24100,
            'wing_ce': 24400,
            'wing_pe': 24000,
            'width_pts': 100,
            'spot': 24139.15,
            'distance_to_short_ce_pts': 160.85,
            'distance_to_short_pe_pts': 39.15,
            'distance_to_wing_ce_pts': 260.85,
            'distance_to_wing_pe_pts': 139.15,
            'expiry': '2026-08-25',
            '0dte': True,
            'monthly_expiry': True,
            'opened_at': '2026-08-25 09:00:40',
            'net_credit': 3264.95,
            'max_loss': 3235.05,
            'status': 'CE_160.85pts_OTM_GREEN_PE_39.15pts_OTM_19.15_above_24120_trigger_24.15_above_24115_close_trigger',
            'tight_side_watch': 'PE_24100_INSIDE_YELLOW_zone_19.15pts_above_24120_trigger_24.15pts_close_buffer_tightened_6pts_vs_11_00'
        },
        {
            'strategy': 'BANKNIFTY Iron Condor',
            'short_strikes': [57600, 57400],
            'wings': [57700, 57300],
            'width_pts': 100,
            'spot': 57443.60,
            'distance_to_short_ce_pts': 156.40,
            'distance_to_short_pe_pts': 43.60,
            'distance_to_wing_ce_pts': 256.40,
            'distance_to_wing_pe_pts': 143.60,
            'expiry': '2026-08-25',
            '0dte': True,
            'monthly_expiry': True,
            'opened_at': '2026-08-25 09:00:40',
            'net_credit': 2325.30,
            'max_loss': 674.70,
            'status': 'CE_156.40pts_OTM_GREEN_MAJOR_DEESCALATION_PE_43.60pts_OTM_23.60_above_57420_trigger_28.60_above_57415_close_trigger',
            'tight_side_watch': 'PE_57400_INSIDE_YELLOW_zone_23.60pts_above_57420_trigger_28.60pts_close_buffer_tightened_51pts_vs_11_00'
        }
    ],
    'risk_budget_pct': 2.0,
    'tuesday_posture': 'normal',
    'monthly_expiry_note': 'Aug 25 2026 = last Tuesday of month = monthly expiry for NIFTY/BANKNIFTY Aug contracts. Combined with weekly = 0DTE MONTHLY close. Gamma risk highest of month. Hold short-vol structures; do not add.',
    'opening_buffer_note': (
        'Opening buffer 09:15-09:30 ended at 09:30:18. Now 110 min into regular session, 4h10m to square-off. '
        '5-min ACTION vs 11:00 tick: SUSTAINED DOWNWARD DRIFT, NOT spike-and-rejection. '
        'BANKNIFTY -51.10 pts (57494.70 -> 57443.60) over 3+ consecutive refreshes all below 57460. '
        'NIFTY -6.05 pts (24145.20 -> 24139.15). VIX 11.47->11.43 (-0.04, flat). '
        'BANKNIFTY 57600 short CE went 105.30 -> 156.40 OTM (MAJOR DE-ESCALATION). '
        'BANKNIFTY 57400 short PE went 94.70 -> 43.60 OTM (now 28.60 above 57415 close trigger, INSIDE YELLOW zone). '
        'NIFTY 24300 short CE went 154.80 -> 160.85 OTM (further GREEN). '
        'NIFTY 24100 short PE went 45.20 -> 39.15 OTM (now 24.15 above 24115 close trigger, INSIDE YELLOW zone). '
        'Hard trigger 57580 cleared with 136.40 buffer (was 85.30 at 11:00).'
    ),
    'reversal_note': (
        'SUSTAINED 3+ REFRESH DOWNWARD DRIFT, CONTRAST WITH 10:55 SPIKE-AND-REJECTION. '
        '10:55 saw spike to 57576.10 (10:54:55), then -2.60 pullback to 57573.50 (10:55:26) — REJECTION pattern. '
        '11:00 saw continued pullback to 57494.70 — STRUCTURAL REVERSAL. Now at 11:05, BANKNIFTY has drifted '
        'further to 57443.60 with 3+ consecutive refreshes all below 57460. '
        'Total BN move from 10:55 spike to 11:05 = -129.90 pts over 10 min. '
        'Today intraday BN range = 57231.25 to 57653.85 (422 pts). '
        'Current 57443.60 is at 50th percentile — at midpoint of today range, not extreme. '
        'The market has found a NEW EQUILIBRIUM in the lower half of the range. '
        'NIFTY 24139.15 is at 29th percentile of today range (24115.45 to 24198.25). '
        'Both structures are in safe territory structurally. Theta continues to work for us — '
        'BN 57600 CE went from 26.50 OTM at 10:55 to 156.40 OTM at 11:05 = MAJOR theta win. '
        'PE side got tighter but still has 24-29 pt buffer above close triggers. '
        'The trade is: hold and let theta accelerate, with hard PE close triggers at 57415/24115 as the line in the sand.'
    ),
    'escalation_rule': (
        'PE-side CLOSE triggers (UNCHANGED): if BANKNIFTY<57415 or NIFTY<24115, CLOSE respective IC/IB PE side. '
        'BANKNIFTY currently 28.60 above (tightened from 79.70, safe with 28-pt buffer). '
        'NIFTY currently 24.15 above (tightened from 30.20, safe with 24-pt buffer). '
        'CE-side YELLOW zone: NIFTY in 24250-24300 OR BANKNIFTY in 57550-57600 = watch closely. '
        'BANKNIFTY currently 106.40 below 57550 (GREEN safe, was 55.30 below at 11:00). '
        'NIFTY currently 110.85 below 24250 (GREEN safe, was 104.80 below). '
        'CE-side RED zone: NIFTY>24300 OR BANKNIFTY>57600 = close CE side. NOT triggered. '
        'HARD TRIGGER 57580: BANKNIFTY is 136.40 below (was 85.30 at 11:00). '
        '10:55 sustained-trigger rule (BN>57570 for 2+ refreshes) RESCINDED — BN no longer in yellow zone. '
        'NEW sustained-pullback watch: if BANKNIFTY<57430 for 2+ consecutive refreshes, '
        'consider pre-emptive PE-side close. Currently 13.60 above. '
        'Time triggers: 13:30 no new entries (2h25m), 14:30 consider 0DTE close (3h25m), 15:15 square off (4h10m).'
    ),
    'tick_summary_11_05': (
        '21st HOLD tick of the day. Bias=neutral. SUSTAINED 3+ REFRESH DOWNWARD DRIFT vs 11:00. '
        'BANKNIFTY -51.10 pts (57494.70 -> 57443.60, -0.89% / 0.89 sigma, sustained over 3+ refreshes all below 57460). '
        'NIFTY -6.05 pts (24145.20 -> 24139.15, -0.07 sigma). VIX 11.47->11.43 (-0.04, flat). '
        'BANKNIFTY 57600 short CE MAJOR DE-ESCALATION: 105.30 -> 156.40 OTM (was already GREEN, now DEEPER GREEN, 0.27% of spot). '
        'BANKNIFTY 57400 PE: 94.70 -> 43.60 OTM (now 28.60 above 57415 close trigger, INSIDE YELLOW zone, tightened 51 pts). '
        'NIFTY 24300 CE: 154.80 -> 160.85 OTM (further GREEN). '
        'NIFTY 24100 PE: 45.20 -> 39.15 OTM (now 24.15 above 24115 close trigger, INSIDE YELLOW zone, tightened 6 pts). '
        'PE buffers getting thin (24-29 pts) but still above close triggers. '
        'CE side massively de-escalated. Range regime intact, 0DTE monthly expiry theta accelerating. '
        'Max loss combined 3,910 INR (3.7% cash) unchanged. '
        'HARD TRIGGER 57580 cleared with 136.40 buffer. '
        'PE close triggers at 57415/24115 unchanged. '
        'NEW sustained-pullback watch: if BN<57430 for 2+ refreshes, pre-emptive PE close. '
        '21st HOLD tick. Both spots at midpoints of today intraday range (BN 50th, NF 29th percentile) — not extreme.'
    )
}

# Save previous decision to history if different
old_dec = state.get('last_decision', {})
if old_dec.get('ist_time') != new_decision['ist_time']:
    hist_entry = {
        'ist_time': old_dec.get('ist_time'),
        'bias': old_dec.get('bias'),
        'note': old_dec.get('note'),
        'actions': old_dec.get('actions', [])
    }
    if 'history' not in state:
        state['history'] = []
    state['history'].append(hist_entry)

state['last_decision'] = new_decision
state['today_date'] = '2026-08-25'
state['call_count_today'] = state.get('call_count_today', 0) + 1

with open(path, 'w', encoding='utf-8') as f:
    json.dump(state, f, ensure_ascii=False, indent=2)

print('OK: wrote last_decision at ' + new_decision['ist_time'] + ', call_count_today=' + str(state['call_count_today']))
print('history len: ' + str(len(state.get('history', []))))
