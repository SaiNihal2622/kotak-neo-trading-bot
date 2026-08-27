import json
from datetime import datetime, timedelta

path = r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json'
with open(path, 'r', encoding='utf-8') as f:
    data = json.load(f)

# IST = UTC+5:30
ist = datetime(2026, 8, 25, 15, 20, 55)
ts_utc = (ist - timedelta(hours=5, minutes=30)).strftime('%Y-%m-%dT%H:%M:%SZ')
ist_str = ist.strftime('%Y-%m-%d %H:%M:%S')

new_decision = {
    'ts': ts_utc,
    'ist_time': ist_str,
    'bias': 'cautious',
    'source': 'mavis',
    'max_positions': 0,
    'actions': [],
    'note': 'post_15_15_eod_bell_no_positions_pre_15_30_market_close',
    'reasoning': f'Tick at {ist_str} IST on Tue 2026-08-25 [0DTE MONTHLY EXPIRY DAY - 5 MIN PAST 15:15 EOD BELL, 10 MIN TO 15:30 MARKET CLOSE]. 110 min after 13:30 entry cutoff, 440 min into regular session, 50 min post force-square mark, 5 min PAST 15:15 square-off bell, 10 min to 15:30 market close. market_session=closing (in-valid-set per spec). NO STATE CHANGE vs prior tick (73->74): open_positions still EMPTY, cash 100229 INR, realized_pnl 229 INR (+0.23% day). Live NIFTY ~24260 (last 24260.05, range 24115-24267 today), Live BN ~57454 (last 57454.10, range 57231-57654 today), VIX 11.10 (calm, <12). Range regime both underlyings [NIFTY conf=0.7 range=0.62%, BANKNIFTY conf=0.7 range=0.74%]. 5d change: NIFTY +0.75% (slight up trend), BANKNIFTY +0.37% (flat). Macro: no events, no blackout. Research: still unavailable. No monday_brief (Tue). DECISION: HOLD ALL [74th tick of day, POST 15:15 EOD BELL]. (1) No positions to manage - force-square fired 14:30:03, all 2 ICs closed. (2) Post 13:30 cutoff = no new entries. (3) POST 15:15 EOD = no new 0DTE positions allowed (intraday square-off complete). (4) Only 10 min to 15:30 market close - no new positions. (5) Strategy day EXHAUSTED. Day PnL +229 INR. NEXT TICK TRIGGERS: (a) Optional 5-min silent ticks till 15:30 market close (1 final tick max). (b) EOD 15:30 - market close. (c) Manual review of day PnL +229 INR. (d) Prep for tomorrow Wed 2026-08-26 (no expiry, weekly options).',
    'candle_regime_evidence': {
        'NIFTY': {
            'regime': 'range',
            'confidence': 0.7,
            'reason': 'range=0.62% tight + vix=11.1 low',
            '5d_change_pct': 0.75,
            'range_pct': 0.62,
            'today_move_pts': 84.55,
            'trend': 'up'
        },
        'BANKNIFTY': {
            'regime': 'range',
            'confidence': 0.7,
            'reason': 'range=0.74% tight + vix=11.1 low',
            '5d_change_pct': 0.37,
            'range_pct': 0.74,
            'today_move_pts': 87.2,
            'trend': 'flat'
        }
    },
    'macro_evidence': {
        'in_blackout': False,
        'next_event': None,
        'events_next_7d': []
    },
    'research_evidence': {
        'available': False,
        'note': 'research not available [Kotak PDF download failed], skipped research bias'
    },
    'monday_brief_evidence': {
        'applicable': False,
        'note': 'Tuesday - Monday brief not consulted'
    },
    'position_evidence': [],
    'executor_status': {
        'standalone_executor': 'dead_3d_no_orders_since_2026-08-22',
        'in_process_resilient': 'ACTIVE_no_new_activity_post_force_square',
        'force_square_backstop': 'FIRED_14:30:03_2026-08-25_all_2_ICs_closed',
        'working_exit': 'force_square_completed'
    },
    'tick_summary_15_20': '74th tick of day, 5 min PAST 15:15 EOD BELL, 10 min to 15:30 market close. Bias=cautious. NO CHANGE vs 15:15: open_positions still EMPTY. cash 100229 INR, realized_pnl 229 INR. Live NIFTY ~24260, BN ~57454. VIX 11.10. Cycle 10977+ latest. REASON FOR HOLD: (1) No positions to manage (force-square fired 14:30:03). (2) Post 13:30 cutoff = no new entries. (3) Post 15:15 EOD bell = no new 0DTE positions (intraday square-off complete). (4) Only 10 min to market close - no setup. (5) Strategy day EXHAUSTED. Day PnL +229 INR. NEXT: 1 final tick at 15:25-15:30, then EOD review.',
    'timestamp': ts_utc,
    'confidence': 0.95,
    'risk_budget_pct': 0.0,
    'rationale': 'HOLD ALL - 74th tick, 5 min past 15:15 EOD bell, identical state to 15:15: force-square fired 14:30:03-04, all 2 ICs closed. open_positions still empty. Post 13:30 cutoff, no new entries. Past 15:15 EOD = 0DTE intraday square-off complete. Only 10 min to 15:30 close - no new positions. Day PnL +229 INR. Silent monitoring. Next: 1 final tick at 15:25-15:30, then EOD review.'
}

# Replace last_decision
data['last_decision'] = new_decision
# Bump call_count
data['call_count_today'] = 74

# Append to history (concise form)
data['history'].append({
    'ist_time': ist_str,
    'bias': 'cautious',
    'note': 'post_15_15_eod_bell_no_positions_pre_15_30_market_close',
    'actions': []
})

# Also append to decisions
data['decisions'].append({
    'ist_time': ist_str,
    'bias': 'cautious',
    'note': 'HOLD_ALL_post_15_15_eod_bell_no_positions_pre_15_30_close_day_PnL_229_INR_force_square_fired_14_30_03',
    'actions': []
})

with open(path, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print('OK: last_decision updated, history appended, call_count=74')
print('last_decision ist_time:', data['last_decision']['ist_time'])
print('history entries:', len(data['history']))
print('decisions entries:', len(data['decisions']))
