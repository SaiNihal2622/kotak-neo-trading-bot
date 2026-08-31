"""
One-shot update of brain_state.json -> last_decision.
Avoids the "duplicate history: [" pitfall from memory note (2026-08-28 13:40).
Reads the file, replaces last_decision in-place, writes back atomically.
"""
import json
import sys
from pathlib import Path

PATH = Path(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json")

NEW_LAST_DECISION = {
    "ts": "2026-08-28T08:15:00Z",
    "timestamp": "2026-08-28T08:15:00Z",
    "ist_time": "2026-08-28 13:45:00",
    "bias": "neutral",
    "source": "mavis",
    "max_positions": 0,
    "actions": [],
    "note": "regular_1345_5min_nochange_observation_FORMAL_SKIP_FIRM_BINDS_holds_vix_10.73_calm_1.0x_plus_0.005_from_1340s_10.725_essentially_flat_nifty_24111.85_yfinance_close_vs_prev_close_24090.85_gap_plus_0.09pct_within_0.5pct_bnf_57391.25_yfinance_close_vs_prev_close_57509.95_gap_minus_0.21pct_within_0.5pct_5d_range_pct_nifty_0.46pct_bnf_0.58pct_5d_trend_both_flat_candle_regime_both_range_conf_0.7_textbook_condor_day_per_regime_macro_no_blackout_monthly_nifty_expiry_104min_at_15_30_0dte_gamma_risk_extreme_india_gdp_tomorrow_1664min_us_futures_still_plus_1.29pct_above_0.4pct_threshold_no_resolution_4h40m_above_threshold_path_bug_NOT_seen_in_1345_log_tail_30c0fc9_fix_confirmed_working_bot_log_tail_clean_all_skips_per_1330_intraday_cutoff_both_scanner_processes_blocking_tick_count_advancing_conservative_override_vix_above_13_or_gap_above_0.5pct_still_false_today_otherwise_eligible_bias_neutral_0pct_new_risk_0_open_positions_clean_slate_capital_109978_realized_9978_bot_alive_TIME_WINDOW_BINDING_NOW_1345_15min_past_1330_no_new_entries_cutoff_45min_before_1430_force_square_off_104min_before_1530_monthly_nifty_expiry_0dte_gamma_risk_extreme_FORMAL_SKIP_FOR_DAY_FIRM_AND_BINDING_per_1315_plan_no_fresh_entry_today_no_reassessment_needed_next_meaningful_action_1430_force_square_off_irrelevant_with_0_positions_or_tomorrow_0825_daily_maintenance_0830_daily_start",
    "market_session": "regular",
    "vix": 10.73,
    "risk_budget_pct": 0,
    "bias_decision": "neutral",
    "macro_in_blackout": False,
    "decision_summary": "13:45 IST 5-min nochange observation tick per the standard cron schedule. Last decision 13:40:45 IST (5 min ago) was a nochange observation tick that held FORMAL_SKIP_FOR_DAY_FIRM_AND_BINDING established at 13:30 (when 13:30 no-new-entries cutoff REACHED). 13:45 is the next scheduled 5-min cron tick. Key facts (13:40 -> 13:45, 5 min delta): (a) VIX 10.73 (+0.005 from 13:40s 10.725 - essentially flat, calm 1.0x mult unchanged). (b) candle_regime both still range conf 0.7 (textbook condor day per regime). (c) 0 open positions unchanged. (d) Capital 1,09,978 INR, realized +9,978 INR. (e) No macro blackout (monthly NIFTY expiry 104 min away, not yet in 60-min blackout window; India GDP tomorrow 17:30 = 1664 min away). (f) Bot tick_count advancing on both scanner processes (cycles 9448/9454/9460/9466/9472 on process A, cycles 445/451/457/463/469 on process B per 13:42-13:44 log tail). (g) Bot log tail at 13:45: all entries are 'skip: intraday mode - no_new_trades_after (13:30) hit' for both scanner processes. LiveKotak heartbeats firing every ~30s on both processes (latest tick_count ~106,466 + 19,840 at 13:44:39/41). (h) Path bug NOT seen in 13:45 log tail - 30c0fc9 fix confirmed working. No force-action check failed, no brain-action check failed warnings. Both action channels working as designed. Two persistent blockers (unchanged from 13:15/13:20/13:25/13:30/13:35/13:40): (1) US futures +1.29% > 0.4% threshold - BLOCK state from 13:30:02/56 still in effect. 4h 40m above threshold, no resolution. 09:45 plans contingency FIRM. (2) STILL BINDING: 13:30 no-new-entries cutoff REACHED 15 min ago. Conservative override (VIX>13 OR gap>0.5%) still FALSE - market is otherwise eligible but execution channels + TIME-WINDOW CONSTRAINTS preclude new entry. 14:30 force-square-off is 45 min away. 15:30 monthly NIFTY expiry is 104 min away. Even if all blockers cleared, no new entry can be placed today. 13:15 FORMAL_SKIP_FOR_DAY_FIRM_AND_BINDING holds at 13:45. No new capital at risk today. No reassessment needed before 14:30 force-square-off.",
    "rationale": "13:45 IST 5-min nochange observation tick per the standard cron schedule. Last decision 13:40:45 IST (5 min ago) held FORMAL_SKIP_FOR_DAY_FIRM_AND_BINDING. 13:45 is the next scheduled 5-min cron tick to keep brain_actions.json channel fresh. Key facts (13:40 -> 13:45, 5 min delta): (a) VIX 10.73 (+0.005 from 13:40s 10.725 - essentially flat, calm 1.0x mult). (b) candle_regime both still range conf 0.7 (NIFTY 5d range_pct 0.46%, BNF 0.58% per yfinance - both TIGHT range regime). (c) 0 open positions unchanged. (d) No macro blackout. (e) Bot tick_count advancing on both scanner processes (cycle 9472 process A, cycle 469 process B per 13:44:54/58 log tail), both alive, both blocking on 13:30 cutoff. (f) Path bug NOT seen in 13:45 log tail - 30c0fc9 fix confirmed working. No force-action check failed, no brain-action check failed warnings. Both action channels working as designed. Two persistent blockers (unchanged from 13:15/13:20/13:25/13:30/13:35/13:40): (1) US futures STILL +1.29% > 0.4% threshold - BLOCK state from 13:30:02/56 still in effect, 4h 40m above threshold, no resolution. 09:45 plans contingency (SKIP entry today entirely if US futures still >0.4%) is FIRM. (2) STILL BINDING: 13:30 no-new-entries cutoff REACHED 15 min ago per intraday.no_new_trades_after - operational constraint blocks new entries independently of US futures BLOCK and 0DTE gamma risk. Conservative override (VIX>13 OR gap>0.5%) still FALSE - market is otherwise eligible. 14:30 force-square-off is 45 min away. 15:30 monthly NIFTY expiry is 104 min away. Even if all blockers cleared, no new entry can be placed today. 13:15 FORMAL_SKIP_FOR_DAY_FIRM_AND_BINDING holds at 13:45. No new capital at risk today. No reassessment needed before 14:30 force-square-off.",
    "risk_budget_reasoning": "Risk budget = 0% new capital for the 13:45 5-min nochange observation tick. (a) 13:45 is the next scheduled 5-min cron tick - not a planned reassessment point per 13:15/13:20/13:25/13:30/13:35/13:40 plans. (b) 13:30 NO-NEW-ENTRIES CUTOFF was REACHED 15 min ago per intraday.no_new_trades_after - bot log confirms skip firing in SCAN loop on both scanner processes. This is the BINDING constraint - no new entries can be placed even if US futures BLOCK clears. (c) US futures STILL +1.29% > 0.4% threshold - BLOCK state from 13:30:02/56 still in effect. 4h 40m above threshold, no resolution. 09:45 plans contingency is FIRM. (d) Path bug NOT seen in 13:45 log tail - 30c0fc9 fix confirmed working. (e) Bot Mavis co-pilot independently BLOCKING on US futures gap. (f) Conservative override (VIX>13 OR gap>0.5%) still FALSE - market is otherwise eligible. (g) Monthly NIFTY expiry 15:30 (104 min) - 0DTE gamma risk now extreme in final 2h. (h) 0 open positions, capital 1,09,978 INR, realized +9,978 INR. (i) Bot alive (tick_count ~106,466 + 19,840 at 13:44:39/41, both blocking). 14:30 force-square-off remains the only working exit (irrelevant with 0 positions, safety net stands). No new capital at risk today. 13:15 FORMAL_SKIP_FOR_DAY_FIRM_AND_BINDING holds at 13:45.",
    "candle_regime_evidence": {
        "NIFTY": {
            "confidence": 0.7,
            "regime": "range",
            "reason": "range=0.46% tight + vix=10.73 low (1.0x mult, +0.005 from 13:40s 10.725 - essentially flat). 5d trend -0.44% (per yfinance, slightly tighter than 13:40s -0.66% - but still flat). Live print 24,111.85 yfinance close vs prev close 24,090.85 = +0.09% gap (within 0.5%). Range regime intact. 5d range_pct 0.46% (same as 13:40). Still textbook 0DTE iron condor setup per regime, but (a) US futures BLOCK active, (b) 13:30 no-new-entries cutoff REACHED 15 min ago - BINDING, (c) 0DTE monthly expiry 104min away - gamma risk extreme. 13:15 FORMAL_SKIP_FIRM_AND_BINDING holds at 13:45 - no new entry today.",
            "range_pct": 0.46,
            "last_close": 24111.85,
            "trend_5d": "flat",
            "change_5d_pct": -0.44
        },
        "BANKNIFTY": {
            "confidence": 0.7,
            "regime": "range",
            "reason": "range=0.58% tight + vix=10.73 low (1.0x mult). 5d trend -0.23% (flat, slightly tighter than 13:40s -0.29%). Live print 57,391.25 yfinance close vs prev close 57,509.95 = -0.21% gap (within 0.5%). BNF slightly improved from 13:40 (57,361 -> 57,391, +30pt move). Range regime intact. 5d range_pct 0.58% (same as 13:40). Still textbook 0DTE iron condor setup per regime, but execution channels closed + TIME-WINDOW CONSTRAINTS (13:30 cutoff REACHED 15 min ago) now BINDING preclude new entry. 13:15 FORMAL_SKIP_FIRM_AND_BINDING holds at 13:45 - no new entry today.",
            "range_pct": 0.58,
            "last_close": 57391.25,
            "trend_5d": "flat",
            "change_5d_pct": -0.23
        }
    },
    "macro_evidence": {
        "upcoming": [
            {
                "importance": 2,
                "minutes_away": 104,
                "name": "monthly_expiry_NIFTY",
                "datetime_ist": "2026-08-28 15:30"
            },
            {
                "importance": 2,
                "minutes_away": 1664,
                "name": "india_gdp",
                "datetime_ist": "2026-08-29 17:30"
            }
        ],
        "in_blackout": False,
        "interpretation": "No near-term event risk in the 60-min blackout window. Monthly NIFTY expiry 104 min away at 15:30 (0DTE) - elevated gamma/vol risk in the last 2h, but not in macro blackout (60-min before window not yet reached - that triggers at 14:30 which is also force-square-off time). India GDP tomorrow 17:30, well outside window. Macro is QUIET. The 13:30 no-new-entries cutoff is a separate operational constraint (not a macro event) - was REACHED 15 min ago, still BINDING. The 14:30 force-square-off is another operational constraint - 45 min away. US futures +1.29% > 0.4% threshold is a separate cautious overlay from the bot Mavis co-pilot (not macro calendar) - this is the condition that has driven the SKIP-for-day decision. No material change in macro from 13:40 except clock advancing 5 min. 13:15 FORMAL_SKIP_FIRM_AND_BINDING holds at 13:45 - no new event, no new blackout, no reassessment warranted before 14:30 force-square-off."
    },
    "research_evidence": {
        "available": False,
        "fallback": "Research PDF download still failing (kotak_research.download_latest_research_pdf:52 WARNING at 13:45 - could not find derivatives PDF URL). Candle+macro+VIX-only mode. VIX 10.73 (calm, 1.0x multiplier, +0.005 from 13:40s 10.725 - essentially flat). Bot Mavis co-pilot is blocking on US futures +1.29% > 0.4% threshold - BLOCK state from 13:30:02/56 still in effect. 13:30 no-new-entries cutoff was REACHED 15 min ago - this is the BINDING constraint that prevents new entry even if US futures clears. 13:15 FORMAL_SKIP_FIRM_AND_BINDING holds at 13:45. Even if US futures reversed now, the 13:30 cutoff is REACHED and 0DTE monthly expiry 104min away - poor risk/reward for fresh entry. SKIP for today, FIRM AND BINDING at 13:45."
    },
    "open_positions_summary": {
        "note": "0 open positions (clean slate, unchanged since 09:46 IST 2026-08-27 EOD square-off). Capital 1,09,978 INR, realized +9,978 INR for the run-to-date. Today: monthly NIFTY expiry at 15:30 (104 min) - 0DTE structures with extreme gamma risk in last 2h. Regular session 4h 45m in. US futures STILL +1.29% > 0.4% threshold - bot Mavis co-pilot STILL BLOCKING entries (BLOCK state from 13:30:02/56 still in effect). Path bug NOT seen in 13:45 log tail - 30c0fc9 fix confirmed working. 13:15/13:20/13:25/13:30/13:35/13:40 FORMAL_SKIP_FIRM_FOR_DAY is FIRM AND BINDING at 13:45 - 13:30 no-new-entries cutoff REACHED 15 min ago per intraday config. Even if both blockers cleared, no new entry can be placed after 13:30. 0DTE gamma risk extreme. No fresh entry today. Next meaningful action: 14:30 force-square-off (irrelevant with 0 positions), then tomorrow 08:25 daily-maintenance + 08:30 daily-start. Bot alive (tick_count ~106,466 + 19,840 at 13:44:39/41, both blocking).",
        "details": [],
        "max_reached": False,
        "count": 0,
        "max_positions_limit": 2
    },
    "tick_context": {
        "previous_decision_ist": "2026-08-28 13:40:45",
        "previous_decision_bias": "neutral",
        "previous_decision_actions_count": 0,
        "decision_changed": False,
        "decision_change_reason": "13:45 IST 5-min nochange observation tick - same call as 13:15/13:20/13:25/13:30/13:35/13:40 (HOLD, bias=neutral, 0% new risk, 0 actions). The 13:15/13:30 plan said no more reassessments scheduled; 13:45 is the next scheduled 5-min cron tick to keep brain_actions.json channel fresh. All blockers unchanged: US futures STILL +1.29% > 0.4% threshold (BLOCK state from 13:30:02/56 still in effect, 4h 40m above threshold), 13:30 no-new-entries cutoff REACHED 15 min ago (still BINDING), Path bug still not seen in live bot (30c0fc9 fix confirmed working). Conservative override (VIX>13 OR gap>0.5%) still FALSE. 13:15 FORMAL_SKIP_FIRM_AND_BINDING holds at 13:45 - same call, fresh tick, no new info, no new actions, no new risk.",
        "key_change_since_previous": "5 min later (13:40 -> 13:45). VIX 10.73 (+0.005 from 13:40s 10.725, essentially flat - 1.0x mult unchanged). candle_regime both still range conf 0.7 (textbook condor day per regime). 0 open positions unchanged. No macro change. market_session still regular. Bot tick_count advancing on both processes: process A scanned cycles 9448/9454/9460/9466/9472 (13:42:54 to 13:44:54), process B scanned cycles 445/451/457/463/469 (13:42:58 to 13:44:58). LiveKotak heartbeats: process A 13:43:39 tick_count=105539, 13:44:39 tick_count=106466 (+927 in 60s = 15.4 ticks/sec). Process B 13:43:41 tick_count=19200, 13:44:41 tick_count=19840 (+640 in 60s = 10.7 ticks/sec). 13:30 NO-NEW-ENTRIES CUTOFF REACHED 15 min ago - bot SCAN log still shows 'skip: intraday mode - no_new_trades_after (13:30) hit' on both processes. 09:45 plans contingency FIRM since 10:00, reconfirmed at 10:15, observation-only at 10:20/10:25, recovery at 13:15, nochange at 13:20, nochange at 13:25, FIRM AND BINDING at 13:30, holds at 13:35, holds at 13:40, holds at 13:45. 11:30 US cash open did NOT resolve. Bot Mavis co-pilot independently BLOCKING on US futures. 14:30 force-square-off in 45 min, 15:30 monthly expiry in 104 min. Even if all blockers cleared, no new entry today. 13:15 FORMAL_SKIP_FIRM_AND_BINDING holds at 13:45.",
        "log_tail_evidence_intraday_cutoff_active": "2026-08-28 13:42:41.184 | INFO | kotak_bot.data.live_feed:_live_kotak_loop:437 | LiveKotak heartbeat: authed=True subscribed=40 latest=40 tick_count=18600 | 2026-08-28 13:42:54.502 | INFO | __main__:run_paper:1231 | [SCAN] cycle=9448 | skip: intraday mode - no_new_trades_after (13:30) hit | 2026-08-28 13:42:58.681 | INFO | __main__:run_paper:1238 | [SCAN] cycle=445 | skip: intraday mode - no_new_trades_after (13:30) hit | 2026-08-28 13:43:24.539 | INFO | __main__:run_paper:1231 | [SCAN] cycle=9454 | skip: intraday mode - no_new_trades_after (13:30) hit | 2026-08-28 13:43:28.698 | INFO | __main__:run_paper:1238 | [SCAN] cycle=451 | skip: intraday mode - no_new_trades_after (13:30) hit | 2026-08-28 13:43:39.170 | INFO | kotak_bot.data.live_feed:_live_kotak_loop:437 | LiveKotak heartbeat: authed=True subscribed=48 latest=48 tick_count=105539 | 2026-08-28 13:43:41.195 | INFO | kotak_bot.data.live_feed:_live_kotak_loop:437 | LiveKotak heartbeat: authed=True subscribed=40 latest=40 tick_count=19200 | 2026-08-28 13:43:54.609 | INFO | __main__:run_paper:1231 | [SCAN] cycle=9460 | skip: intraday mode - no_new_trades_after (13:30) hit | 2026-08-28 13:43:58.731 | INFO | __main__:run_paper:1238 | [SCAN] cycle=457 | skip: intraday mode - no_new_trades_after (13:30) hit | 2026-08-28 13:44:24.658 | INFO | __main__:run_paper:1231 | [SCAN] cycle=9466 | skip: intraday mode - no_new_trades_after (13:30) hit | 2026-08-28 13:44:28.747 | INFO | __main__:run_paper:1238 | [SCAN] cycle=463 | skip: intraday mode - no_new_trades_after (13:30) hit | 2026-08-28 13:44:39.186 | INFO | kotak_bot.data.live_feed:_live_kotak_loop:437 | LiveKotak heartbeat: authed=True subscribed=48 latest=48 tick_count=106466 | 2026-08-28 13:44:41.214 | INFO | kotak_bot.data.live_feed:_live_kotak_loop:437 | LiveKotak heartbeat: authed=True subscribed=40 latest=40 tick_count=19840 | 2026-08-28 13:44:54.708 | INFO | __main__:run_paper:1231 | [SCAN] cycle=9472 | skip: intraday mode - no_new_trades_after (13:30) hit | 2026-08-28 13:44:58.786 | INFO | __main__:run_paper:1238 | [SCAN] cycle=469 | skip: intraday mode - no_new_trades_after (13:30) hit. Bot log tail at 13:45 is CLEAN: all entries are 'skip: intraday mode - no_new_trades_after (13:30) hit' for both scanner processes (cycles 9448/9454/9460/9466/9472 on process A, cycles 445/451/457/463/469 on process B). LiveKotak heartbeat firing every ~30s on both processes. No force-action check failed, no brain-action check failed warnings. Both action channels working as designed."
    },
    "actions_count": 0
}

def main():
    raw = PATH.read_text(encoding="utf-8")
    data = json.loads(raw)
    # Sanity: history key must exist (don't accidentally delete it)
    assert "history" in data, "brain_state.json lost its history key - ABORT"
    # Sanity: only ONE history key at top level
    assert sum(1 for k in data if k == "history") == 1, "duplicate history key - ABORT"
    # Replace last_decision in place
    data["last_decision"] = NEW_LAST_DECISION
    # Write back atomically
    tmp = PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(PATH)
    # Verify
    with PATH.open("r", encoding="utf-8") as f:
        verified = json.load(f)
    assert verified["last_decision"]["ist_time"] == "2026-08-28 13:45:00"
    assert verified["last_decision"]["actions_count"] == 0
    assert sum(1 for k in verified if k == "history") == 1
    history_len = len(verified["history"])
    print(f"OK: last_decision updated to 13:45, history preserved ({history_len} entries)")

if __name__ == "__main__":
    main()
