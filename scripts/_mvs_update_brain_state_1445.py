"""One-shot brain_state.json update for 14:45 IST trader-desk tick.

Per the safe load-mutate-dump pattern documented in AGENTS.md / known-issues
register, this avoids the duplicate `history: [` edit pitfall.
"""
import json
import pathlib
import sys
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))
p = pathlib.Path(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json")

data = json.loads(p.read_text(encoding="utf-8-sig"))

# Archive previous last_decision to history
prev = data.get("last_decision")
ist_now = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
ts_now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

if prev and isinstance(prev, dict):
    archived = dict(prev)
    archived["archived_from"] = "last_decision"
    archived["archived_at"] = ist_now
    data["history"] = [archived] + list(data.get("history", []))

new_decision = {
    "ts": ts_now,
    "timestamp": ts_now,
    "ist_time": ist_now,
    "bias": "neutral",
    "source": "mavis",
    "max_positions": 0,
    "actions": [],
    "note": "regular_1445_5min_nochange_observation_FORMAL_SKIP_FIRM_BINDS_holds_vix_10.885_calm_1.0x_plus_0.025_from_1440s_10.86_essentially_flat_nifty_24114.70_yfinance_close_vs_prev_close_24114.70_gap_0.0pct_within_0.5pct_bnf_57401.20_yfinance_close_vs_prev_close_57401.20_gap_0.0pct_within_0.5pct_5d_range_pct_nifty_0.46pct_bnf_0.58pct_tight_range_5d_trend_nifty_flat_minus_0.43pct_bnf_flat_minus_0.22pct_candle_regime_both_range_conf_0.7_textbook_condor_day_per_regime_macro_no_blackout_monthly_nifty_expiry_43min_at_15_30_0dte_gamma_risk_extreme_in_final_hour_india_gdp_tomorrow_1603min_us_futures_still_plus_1.29pct_above_0.4pct_threshold_no_resolution_5h45m_above_threshold_path_bug_NOT_seen_in_1445_log_tail_30c0fc9_fix_confirmed_working_bot_log_tail_clean_all_skips_per_1330_intraday_cutoff_both_scanner_processes_blocking_tick_count_advancing_process_A_137769_process_B_40400_at_14_45_40_42_conservative_override_vix_above_13_or_gap_above_0.5pct_still_false_today_otherwise_eligible_bias_neutral_0pct_new_risk_0_open_positions_clean_slate_capital_109978_realized_9978_bot_alive_TIME_WINDOW_BINDING_NOW_1445_76min_past_1330_no_new_entries_cutoff_16min_into_1430_force_square_off_window_30min_before_1515_square_off_43min_before_1530_monthly_nifty_expiry_0dte_gamma_risk_extreme_FORMAL_SKIP_FOR_DAY_FIRM_AND_BINDING_per_1315_plan_no_fresh_entry_today_no_reassessment_needed_next_meaningful_action_1515_square_off_no_op_with_0_positions_then_1530_monthly_expiry_then_tomorrow_0825_daily_maintenance_0830_daily_start",
    "market_session": "regular",
    "vix": 10.885,
    "risk_budget_pct": 0,
    "bias_decision": "neutral",
    "macro_in_blackout": False,
    "decision_summary": "14:45 IST 5-min nochange observation tick (5 min after 14:40). VIX 10.885 (calm, 1.0x mult, +0.025 from 14:40s 10.86 - essentially flat). candle_regime both still range conf 0.7 (NIFTY 5d range_pct 0.46%, BNF 0.58% per yfinance - tight range). 0 open positions unchanged. No macro blackout (monthly NIFTY expiry 43 min away - in 60-min pre-event window since 14:30, but bot's macro.in_blackout flag still reads false). Bot tick_count advancing on both scanner processes (137,769 + 40,400 at 14:45:40/42), both alive, both blocking on 13:30 cutoff. Bot log tail CLEAN: all SCAN entries are skip: intraday mode - no_new_trades_after (13:30) hit. Path bug NOT seen - 30c0fc9 fix confirmed working. Both action channels working. Two persistent blockers unchanged: (1) US futures STILL +1.29% > 0.4% threshold - BLOCK state from 13:30:02/56 still in effect, 5h 45m above threshold, no resolution. (2) 13:30 no-new-entries cutoff REACHED 76 min ago - BINDING. 14:30 force-square-off ACTIVE for 16 min - no-op with 0 positions. Conservative override (VIX>13 OR gap>0.5%) still FALSE. 0DTE monthly expiry 43 min away - gamma risk extreme. 13:15 FORMAL_SKIP_FIRM_AND_BINDING holds at 14:45 - no new entry today. Next meaningful action: 15:15 square_off (no-op), 15:30 monthly expiry, then tomorrow 08:25 daily-maintenance + 08:30 daily-start.",
    "rationale": "14:45 IST 5-min nochange observation tick - same call as 14:00/14:30/14:35/14:40. VIX 10.885 (+0.025 from 14:40s 10.86 - essentially flat calm, 1.0x mult unchanged). candle_regime both still range conf 0.7 (NIFTY 5d range_pct 0.46%, BNF 0.58% per yfinance - tight range regime, textbook 0DTE condor day per regime). 0 open positions unchanged. No macro blackout per bot's macro.in_blackout flag (monthly NIFTY expiry 43 min away at 15:30 - 60-min pre-event window started at 14:30 so we are 16 min INTO it per settings.yaml event_blackout_min_before=60, but the live state still reports in_blackout=false; in absolute terms for a manual trader this would now be a hard block). Bot tick_count advancing on both scanner processes (process A 137769 at 14:45:40, process B 40400 at 14:45:42), both alive, both blocking on 13:30 cutoff. Bot log tail at 14:45 CLEAN: all SCAN entries are skip: intraday mode - no_new_trades_after (13:30) hit on both processes. Path bug NOT seen in 14:45 log tail - 30c0fc9 fix confirmed working. No force-action check failed, no brain-action check failed warnings. Both action channels working as designed. Two persistent blockers unchanged from 14:40: (1) US futures STILL +1.29% > 0.4% threshold - BLOCK state from 13:30:02/56 still in effect, 5h 45m above threshold, no resolution. 09:45 plans contingency FIRM. (2) STILL BINDING: 13:30 no-new-entries cutoff REACHED 76 min ago per intraday.no_new_trades_after. 14:30 FORCE-SQUARE-OFF ACTIVE for 16 min - bot's main loop called square_off_all() which is a no-op with 0 positions. Conservative override (VIX>13 OR gap>0.5%) still FALSE - market is otherwise eligible. Even if all blockers cleared, no new entry can be placed after 13:30 today. 0DTE monthly expiry 43 min away - gamma risk extreme in final hour. 15:15 square_off in 30 min (no-op with 0 positions), 15:30 monthly expiry in 43 min. 13:15 FORMAL_SKIP_FIRM_AND_BINDING holds at 14:45. No new capital at risk today. No reassessment needed before 15:15 square_off or 15:30 monthly expiry.",
    "risk_budget_reasoning": "Risk budget = 0% new capital for the 14:45 5-min nochange observation cron tick. (a) 13:30 NO-NEW-ENTRIES CUTOFF was REACHED 76 min ago per intraday.no_new_trades_after - bot log confirms skip firing in SCAN loop on both scanner processes. This is the BINDING constraint. (b) US futures STILL +1.29% > 0.4% threshold - BLOCK state from 13:30:02/56 still in effect. 5h 45m above threshold, no resolution. 09:45 plans contingency is FIRM. (c) Path bug NOT seen in 14:45 log tail - 30c0fc9 fix confirmed working. (d) Bot Mavis co-pilot independently BLOCKING on US futures gap. (e) Conservative override (VIX>13 OR gap>0.5%) still FALSE - market is otherwise eligible. (f) Monthly NIFTY expiry 15:30 (43 min) - 0DTE gamma risk now extreme in final hour; 16 min into 60-min pre-event window per settings.yaml event_blackout_min_before. (g) 0 open positions, capital 1,09,978 INR, realized +9,978 INR. (h) Bot alive (tick_count 137,769 + 40,400 at 14:45:40/42, both blocking). (i) 14:30 force-square-off ACTIVE for 16 min - irrelevant with 0 positions. (j) Bot log tail CLEAN. No new capital at risk today. 13:15 FORMAL_SKIP_FIRM_AND_BINDING holds at 14:45.",
    "candle_regime_evidence": {
        "NIFTY": {
            "confidence": 0.7,
            "regime": "range",
            "reason": "range=0.46% tight + vix=10.885 low (1.0x mult, +0.025 from 14:40s 10.86 - essentially flat). 5d trend -0.43% (per yfinance - flat). Live print 24,114.70 yfinance close vs prev close 24,114.70 = 0.0% gap (within 0.5%). Range regime intact. 5d range_pct 0.46% (tight). Still textbook 0DTE iron condor setup per regime, but (a) US futures BLOCK active, (b) 13:30 no-new-entries cutoff REACHED 76 min ago - BINDING, (c) 0DTE monthly expiry 43min away - gamma risk extreme, (d) 14:30 FORCE-SQUARE-OFF ACTIVE - irrelevant with 0 positions, (e) 16 min into 60-min pre-event window per settings.yaml. 13:15 FORMAL_SKIP_FIRM_AND_BINDING holds at 14:45 - no new entry today.",
            "range_pct": 0.46,
            "last_close": 24114.70,
            "trend_5d": "flat",
            "change_5d_pct": -0.43,
        },
        "BANKNIFTY": {
            "confidence": 0.7,
            "regime": "range",
            "reason": "range=0.58% tight + vix=10.885 low (1.0x mult, +0.025 from 14:40s 10.86 - essentially flat). 5d trend -0.22% (per yfinance - flat). Live print 57,401.20 yfinance close vs prev close 57,401.20 = 0.0% gap (within 0.5%). BNF unchanged from 14:40 in regime terms. Range regime intact. 5d range_pct 0.58% (tight). Still textbook 0DTE iron condor setup per regime, but execution channels closed + TIME-WINDOW CONSTRAINTS (13:30 cutoff REACHED 76 min ago + 14:30 FORCE-SQUARE-OFF ACTIVE + 60-min pre-event window 16 min in) now BINDING preclude new entry. 13:15 FORMAL_SKIP_FIRM_AND_BINDING holds at 14:45 - no new entry today.",
            "range_pct": 0.58,
            "last_close": 57401.20,
            "trend_5d": "flat",
            "change_5d_pct": -0.22,
        },
    },
    "macro_evidence": {
        "upcoming": [
            {
                "importance": 2,
                "minutes_away": 43,
                "name": "monthly_expiry_NIFTY",
                "datetime_ist": "2026-08-28 15:30",
            },
            {
                "importance": 2,
                "minutes_away": 1603,
                "name": "india_gdp",
                "datetime_ist": "2026-08-29 17:30",
            },
        ],
        "in_blackout": False,
        "interpretation": "No near-term event risk in the 60-min blackout window per bot's macro.in_blackout flag (which still reads false at 14:45). HOWEVER, the 60-min pre-event window for monthly expiry started at 14:30, so we are 16 min INTO the window per settings.yaml event_blackout_min_before=60 - for a manual trader this would now be a hard block. Monthly NIFTY expiry 43 min away at 15:30 (0DTE) - elevated gamma/vol risk in the last hour. India GDP tomorrow 17:30, well outside window. Macro is QUIET in absolute terms. The 13:30 no-new-entries cutoff is a separate operational constraint (not a macro event) - was REACHED 76 min ago, still BINDING. The 14:30 force-square-off is ACTIVE (this tick is 16 min into it) - another operational constraint. US futures +1.29% > 0.4% threshold is a separate cautious overlay from the bot Mavis co-pilot (not macro calendar) - this is the condition that has driven the SKIP-for-day decision. No material change in macro from 14:40 except clock advancing 5 min. 13:15 FORMAL_SKIP_FIRM_AND_BINDING holds at 14:45 - no new event, no new blackout, no reassessment warranted before 15:15 square_off or 15:30 monthly expiry.",
    },
    "research_evidence": {
        "available": False,
        "fallback": "Research PDF download still failing (kotak_research.download_latest_research_pdf:52 WARNING at 14:45 - could not find derivatives PDF URL). Candle+macro+VIX-only mode. VIX 10.885 (calm, 1.0x multiplier, +0.025 from 14:40s 10.86 - essentially flat). Bot Mavis co-pilot is blocking on US futures +1.29% > 0.4% threshold - BLOCK state from 13:30:02/56 still in effect. 13:30 no-new-entries cutoff was REACHED 76 min ago - this is the BINDING constraint that prevents new entry even if US futures clears. 14:30 FORCE-SQUARE-OFF ACTIVE for 16 min - no-op with 0 positions. 60-min pre-event window 16 min in per settings.yaml. Even if US futures reversed now, the 13:30 cutoff is REACHED and 0DTE monthly expiry 43min away - poor risk/reward for fresh entry. SKIP for today, FIRM AND BINDING at 14:45.",
    },
    "open_positions_summary": {
        "note": "0 open positions (clean slate, unchanged since 09:46 IST 2026-08-27 EOD square-off). Capital 1,09,978 INR, realized +9,978 INR for the run-to-date. Today: monthly NIFTY expiry at 15:30 (43 min) - 0DTE structures with extreme gamma risk in last hour. Regular session 6h 15m in. US futures STILL +1.29% > 0.4% threshold - bot Mavis co-pilot STILL BLOCKING entries (BLOCK state from 13:30:02/56 still in effect). Path bug NOT seen in 14:45 log tail - 30c0fc9 fix confirmed working. Bot log tail CLEAN: all SCAN entries are skip: intraday mode - no_new_trades_after (13:30) hit on both scanner processes. 13:15/13:20/13:25/13:30/13:35/13:40/13:45/13:50/14:00/14:30/14:35/14:40 FORMAL_SKIP_FIRM_FOR_DAY is FIRM AND BINDING at 14:45 - 13:30 no-new-entries cutoff REACHED 76 min ago per intraday config. 14:30 FORCE-SQUARE-OFF ACTIVE for 16 min - irrelevant with 0 positions. Even if both blockers cleared, no new entry can be placed after 13:30. 0DTE gamma risk extreme. No fresh entry today. Next meaningful action: 15:15 square_off (no-op with 0 positions), 15:30 monthly expiry, then tomorrow 08:25 daily-maintenance + 08:30 daily-start. Bot alive (tick_count 137,769 + 40,400 at 14:45:40/42, both blocking).",
        "details": [],
        "max_reached": False,
        "count": 0,
        "max_positions_limit": 2,
    },
    "tick_context": {
        "previous_decision_ist": "2026-08-28 14:40:35",
        "previous_decision_bias": "neutral",
        "previous_decision_actions_count": 0,
        "decision_changed": False,
        "decision_change_reason": "14:45 IST 5-min nochange observation cron tick - same call as 14:00/14:30/14:35/14:40 (HOLD, bias=neutral, 0% new risk, 0 actions). The 14:30 force-square-off is a bot-level action (square_off_all in the main loop), not a brain action. With 0 open positions, force-square-off is a NO-OP. The brain just confirms HOLD/0 positions. All blockers unchanged: US futures STILL +1.29% > 0.4% threshold (BLOCK state from 13:30:02/56 still in effect, 5h 45m above threshold), 13:30 no-new-entries cutoff REACHED 76 min ago (still BINDING), 14:30 FORCE-SQUARE-OFF ACTIVE for 16 min (irrelevant with 0 positions), 60-min pre-event window 16 min in per settings.yaml, Path bug still not seen in live bot (30c0fc9 fix confirmed working). Bot log tail CLEAN: all SCAN entries are skip: intraday mode - no_new_trades_after (13:30) hit on both processes. Conservative override (VIX>13 OR gap>0.5%) still FALSE. 13:15 FORMAL_SKIP_FIRM_AND_BINDING holds at 14:45 - same call, fresh tick, no new info, no new actions, no new risk.",
        "key_change_since_previous": "5 min later (14:40 -> 14:45). VIX 10.885 (+0.025 from 14:40s 10.86, essentially flat - 1.0x mult unchanged). candle_regime both still range conf 0.7 (textbook condor day per regime). 0 open positions unchanged. No macro change. market_session still regular. Bot tick_count advancing on both processes: process A heartbeat 14:45:40 tick_count=137769, process B heartbeat 14:45:42 tick_count=40400. LiveKotak heartbeats firing every ~30s on both processes. Bot log tail CLEAN: all SCAN entries are skip: intraday mode - no_new_trades_after (13:30) hit on both processes. 13:30 NO-NEW-ENTRIES CUTOFF REACHED 76 min ago - bot SCAN log still shows skip firing in SCAN loop on both scanner processes. 14:30 FORCE-SQUARE-OFF ACTIVE for 16 min - bot's main loop called square_off_all() which is a no-op with 0 positions. 60-min pre-event window for monthly expiry 16 min in per settings.yaml event_blackout_min_before=60. 09:45 plans contingency FIRM since 10:00, reconfirmed at 10:15, observation-only at 10:20/10:25, recovery at 13:15, nochange at 13:20/13:25, FIRM AND BINDING at 13:30, holds at 13:35/13:40/13:45/13:50/14:00/14:30/14:35/14:40, holds at 14:45. 11:30 US cash open did NOT resolve. Bot Mavis co-pilot independently BLOCKING on US futures. 15:15 square_off in 30 min, 15:30 monthly expiry in 43 min. Even if all blockers cleared, no new entry today. 13:15 FORMAL_SKIP_FIRM_AND_BINDING holds at 14:45.",
        "log_tail_evidence_intraday_cutoff_active": "2026-08-28 14:43:42.579 | INFO | LiveKotak heartbeat: authed=True subscribed=40 latest=40 tick_count=39400 | 2026-08-28 14:44:00.477 | INFO | __main__:run_paper:1231 | [SCAN] cycle=10180 | skip: intraday mode - no_new_trades_after (13:30) hit | 2026-08-28 14:44:04.321 | INFO | __main__:run_paper:1238 | [SCAN] cycle=1177 | skip: intraday mode - no_new_trades_after (13:30) hit | 2026-08-28 14:44:30.546 | INFO | __main__:run_paper:1231 | [SCAN] cycle=10186 | skip: intraday mode - no_new_trades_after (13:30) hit | 2026-08-28 14:44:34.355 | INFO | __main__:run_paper:1238 | [SCAN] cycle=1183 | skip: intraday mode - no_new_trades_after (13:30) hit | 2026-08-28 14:44:40.438 | INFO | LiveKotak heartbeat: authed=True subscribed=48 latest=48 tick_count=137125 | 2026-08-28 14:44:42.600 | INFO | LiveKotak heartbeat: authed=True subscribed=40 latest=40 tick_count=39920 | 2026-08-28 14:45:00.594 | INFO | __main__:run_paper:1231 | [SCAN] cycle=10192 | skip: intraday mode - no_new_trades_after (13:30) hit | 2026-08-28 14:45:04.420 | INFO | __main__:run_paper:1238 | [SCAN] cycle=1189 | skip: intraday mode - no_new_trades_after (13:30) hit | 2026-08-28 14:45:30.646 | INFO | __main__:run_paper:1231 | [SCAN] cycle=10198 | skip: intraday mode - no_new_trades_after (13:30) hit | 2026-08-28 14:45:34.640 | INFO | __main__:run_paper:1238 | [SCAN] cycle=1195 | skip: intraday mode - no_new_trades_after (13:30) hit | 2026-08-28 14:45:40.494 | INFO | LiveKotak heartbeat: authed=True subscribed=48 latest=48 tick_count=137769 | 2026-08-28 14:45:42.734 | INFO | LiveKotak heartbeat: authed=True subscribed=40 latest=40 tick_count=40400 | 2026-08-28 14:46:01.030 | INFO | __main__:run_paper:1231 | [SCAN] cycle=10204 | skip: intraday mode - no_new_trades_after (13:30) hit | 2026-08-28 14:46:04.847 | INFO | __main__:run_paper:1238 | [SCAN] cycle=1201 | skip: intraday mode - no_new_trades_after (13:30) hit. Bot log tail at 14:45 is CLEAN. All SCAN entries are skip: intraday mode - no_new_trades_after (13:30) hit on both scanner processes. LiveKotak heartbeat firing every ~30s on both processes. No force-action check failed, no brain-action check failed warnings. Both action channels working as designed. Path bug NOT seen in 14:45 log tail - 30c0fc9 fix confirmed working.",
    },
    "actions_count": 0,
}

data["last_decision"] = new_decision
data["call_count_today"] = data.get("call_count_today", 0) + 1
data["timestamp"] = ts_now

# Sanity: re-parse
p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
re_parsed = json.loads(p.read_text(encoding="utf-8"))
assert re_parsed["last_decision"]["ist_time"] == ist_now
assert re_parsed["call_count_today"] >= 25
assert len(re_parsed["history"]) >= 22
print(f"OK 14:45 brain_state updated. call_count_today={re_parsed['call_count_today']}, history_len={len(re_parsed['history'])}")
print(f"    last_decision.ist_time={re_parsed['last_decision']['ist_time']}")
print(f"    last_decision.bias={re_parsed['last_decision']['bias']}")
print(f"    last_decision.actions_count={re_parsed['last_decision']['actions_count']}")
print(f"    last_decision.vix={re_parsed['last_decision']['vix']}")
