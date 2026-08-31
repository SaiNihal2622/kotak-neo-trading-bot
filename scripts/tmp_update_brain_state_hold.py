import json
import os

path = r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json'

with open(path, 'r', encoding='utf-8') as f:
    state = json.load(f)

# Update call_count
state['call_count_today'] = 25

# New HOLD last_decision
new_decision = {
    "ts": "2026-08-27T06:51:30Z",
    "ist_time": "2026-08-27 12:21:30",
    "bias": "cautious",
    "source": "mavis",
    "max_positions": 2,
    "actions": [],
    "note": "hold_nifty_comfortable_pe_buffer_46pt_bnf_deep_itm_no_per_leg_close_channel_force_sq_1430_2h09m_max_loss_201_inr_backstop_mavis_force_action_closes_all_no_selective_close",
    "market_session": "regular",
    "vix": 11.18,
    "macro_in_blackout": False,
    "candle_regime_evidence": {
        "NIFTY": {
            "regime": "range",
            "confidence": 0.7,
            "last_close": 24146.4,
            "trend_5d": "flat",
            "change_5d_pct": -0.44,
            "range_pct": 0.68,
            "reason": "range=0.68% tight + vix=11.18 calm (1.0x multiplier); spot 24146.60 (LiveIndia 12:21:18) between shorts 24100/24300 -- RECOVERED +7.30pt from 12:10 tick (was 24139.30); PE buffer 39.30 -> 46.60pt (+7.30pt, now 31.60pt above 15pt trigger, COMFORTABLE), CE buffer 160.70 -> 153.40pt (-7.30pt, very safe). Both legs OTM, range regime well-centered. NIFTY 5d trend flat (-0.44% over 5d), no directional pressure."
        },
        "BANKNIFTY": {
            "regime": "range",
            "confidence": 0.7,
            "last_close": 57597.55,
            "trend_5d": "flat",
            "change_5d_pct": -0.28,
            "range_pct": 0.74,
            "reason": "range=0.74% tight + vix=11.18 calm (1.0x multiplier); spot 57601.60 (LiveIndia 12:21:18) BELOW short PE 57700 by 98.40pt -- DEEP ITM; 3 consecutive lower intraday lows (57623, 57606, 57584) on 1m refreshes -- DOWNTREND. PE buffer -34.20 -> -98.40pt (-64.20pt worse in 11min), CE buffer 234.20 -> 298.40pt (+64.20pt safer). BNF condor MTM ~-1500 INR (PE intrinsic 98.40 vs credit 37.39 = 60.91pt loss PE; offset by CE time value). BNF condor max loss cap 201 INR (spread width - credit) = bounded; if held to expiry still 201 max. 14:30 force-square-off in 2h09m is the natural exit."
        }
    },
    "macro_evidence": {
        "in_blackout": False,
        "upcoming_events": [
            {"name": "monthly_expiry_NIFTY", "datetime_ist": "2026-08-28 15:30", "importance": 2, "minutes_away": 1628},
            {"name": "india_gdp", "datetime_ist": "2026-08-29 17:30", "importance": 2, "minutes_away": 3188}
        ],
        "interpretation": "No near-term event risk. Monthly NIFTY expiry tomorrow 27h08m away. GDP 53h08m away. Both well outside 60min blackout window. Macro quiet, no defensive bias needed. ~2h09m to 14:30 force square-off, ~1h09m to 13:30 no-new-entries cutoff."
    },
    "research_evidence": {
        "available": False,
        "fallback": "Research PDF download still failing (kotak_research.download_latest_research_pdf:52 WARNING, fired again at 12:21:22). Candle+macro+VIX-only mode. VIX 11.18 (DOWN 0.02pt from 11.20 at 12:10, still well in calm range, 1.0x multiplier)."
    },
    "open_positions_summary": {
        "count": 2,
        "details": [
            "NIFTY 0DTE iron condor: short 24300CE/24100PE, long 24400CE/24000PE, width 100, 65 qty per leg, opened 09:30:32 IST at net credit 55.70/unit (max profit 3620 INR, max loss 2880 INR) - HOLD, MTM ~+2050 INR",
            "BANKNIFTY 0DTE iron condor: short 57900CE/57700PE, long 58000CE/57600PE, width 100, 30 qty per leg, opened 09:30:32 IST at net credit 93.29/unit (max profit 2799 INR, max loss 201 INR spread cap, MTM ~-1500 INR currently) - HOLD, 14:30 force-square backstop"
        ],
        "spot_vs_strikes": {
            "nifty": "spot 24146.60 (LiveIndia 12:21:18) between shorts 24100/24300 -- 46.60pt from short PE, 153.40pt from short CE -- +7.30pt UP from 12:10 (was 39.30/160.70) -- PE buffer 39.30 -> 46.60pt (+7.30pt, now 31.60pt above 15pt trigger, COMFORTABLE), CE buffer 160.70 -> 153.40pt (-7.30pt, very safe). NIFTY recovered from 12:10 low, both legs OTM, range regime well-centered.",
            "banknifty": "spot 57601.60 (LiveIndia 12:21:18) BELOW short PE strike 57700 by 98.40pt -- 298.40pt from short CE -- -64.20pt DOWN from 12:10 (was -34.20/234.20) -- PE buffer -34.20 -> -98.40pt (-64.20pt WORSE, BNF DEEPER ITM, 3 consecutive lower intraday lows), CE buffer 234.20 -> 298.40pt (+64.20pt safer). BNF condor MTM loss ~-1500 INR (PE intrinsic bleed exceeds CE time value). Spread-width max loss 201 INR if held to expiry; MTM can exceed this intraday."
        },
        "unrealized_pnl_inr_estimate": {
            "nifty_condor_ltp_based": "~2050",
            "banknifty_condor_ltp_based": "~-1500 (was +1629 at 12:10, MTM swung -3129 INR on BNF -64.20pt move)",
            "total_approx": "~+550 (down from 12:10 +3429 by ~-2879 INR)",
            "note": "NIFTY condor: +7.30pt recovery, range regime intact, MTM +2050 INR. BNF condor: deep ITM on PE side, MTM swung to ~-1500 INR. Net ~+550 INR aggregate. 14:30 force-square-off is the natural exit; spread-width max loss on BNF 201 INR if held to expiry (but MTM can exceed this intraday)."
        },
        "max_reached": True,
        "max_positions_limit": 2,
        "note": "At cap 2/2. CANNOT force-close just BNF: bot's mavis_force_action channel (CLOSE_UNDERLYING=BANKNIFTY or CLOSE_ALL) calls order_mgr.square_off_all which closes BOTH condors. Closing BNF alone would require per-leg close which the current channel does not support. Decision: HOLD both, let 14:30 force-square-off handle the natural exit. BNF max loss spread-width = 201 INR (bounded at expiry); MTM can exceed this intraday but is the cost of waiting. Alternative: CLOSE_ALL via mavis_force_action would close NIFTY too (+2050 profit gone) and BNF, netting roughly MTM -1500 + realized NIFTY +2050 = +550 (close to current MTM aggregate). Letting 14:30 force-square is preferred since NIFTY theta-positive and may improve further."
    },
    "bias_decision": "cautious",
    "risk_budget_pct": 0.0,
    "risk_budget_reasoning": "Risk budget = 0% for new capital: (a) at cap 2/2, (b) only 1h09m to 13:30 no-new-entries cutoff, (c) ~2h09m to 14:30 force-square-off insufficient for new 0DTE trade + opening buffer, (d) BNF breaking down with no per-leg close channel available, (e) macro quiet but BNF momentum negative. Brain escalation to cautious because BNF condor MTM ~-1500 INR (no per-leg close to cut it). Hold-and-let-force-square is the optimal path given the channel limitation.",
    "planned_setup": None,
    "decision_summary": "HOLD both condors at 12:21 IST, regular session, ~2h09m to 14:30 force square-off, ~1h09m to 13:30 no-new-entries cutoff. CRITICAL ARCHITECTURAL FINDING (in-session): The bot does NOT read brain_actions.json for execution. The actual execution channel is mavis_force_action.json (CLOSE_ALL / CLOSE_UNDERLYING=X / PAUSE_BOT / RESUME_BOT), read every 5-30s. CLOSE_UNDERLYING=X calls order_mgr.square_off_all which closes ALL positions (not just the named underlying). Therefore: the 12:10 brain's CLOSE on BNF condor in brain_actions.json was IGNORED by the bot. The only way to force-close the BNF condor is CLOSE_ALL or CLOSE_UNDERLYING=BANKNIFTY, both of which would ALSO close the NIFTY condor (killing ~+2050 INR unrealized profit). Therefore HOLD is the right call. BNF condor MTM ~-1500 INR but spread-width max loss = 201 INR if held to expiry (bounded). NIFTY condor MTM ~+2050 INR, recovering from 12:10 low. Aggregate ~+550 INR. 14:30 force-square will close both naturally. If BNF falls further, loss is bounded by 201 INR spread-width minus time value capture. NIFTY is comfortable, PE buffer 46.60pt (31.60pt above 15pt trigger), CE buffer 153.40pt, both legs OTM, range regime intact. New escalation trigger for future ticks: BNF < 57500 (next major level) -- at that point, the brain should write mavis_force_action.json (NOT brain_actions.json) and use CLOSE_ALL (since per-leg close is unavailable), accepting the NIFTY+2050 forfeit to cap BNF loss. Alternatively, the bot needs a per-leg close channel added to mavis_force_action.json schema."
}

state['last_decision'] = new_decision

# Update history: prepend new entry (no actions, hold)
history_entry = {
    "ts": "2026-08-27T06:51:30Z",
    "ist_time": "2026-08-27 12:21:30",
    "bias": "cautious",
    "actions": [],
    "note": "hold_nifty_comfortable_pe_buffer_46pt_bnf_deep_itm_no_per_leg_close_channel_force_sq_1430_2h09m_max_loss_201_inr_backstop_mavis_force_action_closes_all_no_selective_close"
}

# Replace any prior 12:21 entries (in case of partial write) and prepend
state['history'] = [h for h in state.get('history', []) if h.get('ist_time') != '2026-08-27 12:21:30']
state['history'].insert(0, history_entry)

# Update last_updated_ist
state['last_updated_ist'] = '2026-08-27 12:21:30'

with open(path, 'w', encoding='utf-8') as f:
    json.dump(state, f, indent=2, ensure_ascii=False)

# Verify
with open(path, 'r', encoding='utf-8') as f:
    verify = json.load(f)
print(f'Wrote clean brain_state.json:')
print(f'  call_count_today: {verify["call_count_today"]}')
print(f'  last_decision ist_time: {verify["last_decision"]["ist_time"]}')
print(f'  last_decision bias: {verify["last_decision"]["bias"]}')
print(f'  last_decision actions: {len(verify["last_decision"]["actions"])} (should be 0)')
print(f'  last_decision note: {verify["last_decision"]["note"][:80]}...')
print(f'  history entries: {len(verify["history"])}')
print(f'  last_updated_ist: {verify["last_updated_ist"]}')
