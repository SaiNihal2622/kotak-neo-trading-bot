#!/usr/bin/env python
"""One-shot: update brain_state.json last_decision for 14:30 IST force-square-off tick.

Safe pattern: load dict -> mutate -> dump back. Avoids the known string-edit
pitfall where appending "history": [ to new_string would duplicate it.
"""
import json
import sys
from pathlib import Path

p = Path(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json")

raw = p.read_text(encoding="utf-8-sig")
data = json.loads(raw)

# Sanity: confirm structure is intact
assert "last_decision" in data, "missing last_decision"
assert "history" in data, "missing history"
prev_ist = data["last_decision"]["ist_time"]
print(f"prev last_decision.ist_time = {prev_ist}", flush=True)
print(f"prev call_count_today = {data.get('call_count_today')}", flush=True)
print(f"prev top-level timestamp = {data.get('timestamp')}", flush=True)
print(f"history entries: {len(data['history'])}", flush=True)

# Update top-level fields
data["call_count_today"] = 23
data["timestamp"] = "2026-08-28T09:00:36Z"

# New last_decision for 14:30 IST = force-square-off moment
new_decision = {
    "ts": "2026-08-28T09:00:36Z",
    "timestamp": "2026-08-28T09:00:36Z",
    "ist_time": "2026-08-28 14:30:36",
    "bias": "neutral",
    "source": "mavis",
    "max_positions": 0,
    "actions": [],
    "note": "regular_1430_FORCE_SQUARE_OFF_tick_FORMAL_SKIP_FIRM_BINDS_holds_vix_10.89_calm_1.0x_minus_0.02_from_1400s_10.91_essentially_flat_nifty_24146.05_yfinance_close_vs_prev_close_24090.85_gap_plus_0.23pct_within_0.5pct_bnf_57454.55_yfinance_close_vs_prev_close_57509.95_gap_minus_0.10pct_within_0.5pct_5d_range_pct_nifty_0.25pct_bnf_0.41pct_very_tight_5d_trend_nifty_flat_minus_0.30pct_bnf_flat_minus_0.12pct_candle_regime_both_range_conf_0.7_textbook_condor_day_per_regime_macro_no_blackout_monthly_nifty_expiry_59min_at_15_30_0dte_gamma_risk_extreme_in_final_hour_india_gdp_tomorrow_1619min_us_futures_still_plus_1.29pct_above_0.4pct_threshold_no_resolution_5h30m_above_threshold_path_bug_NOT_seen_in_1430_log_tail_30c0fc9_fix_confirmed_working_bot_log_tail_clean_except_1_transient_getaddrinfo_failed_at_1428_41_known_self_recover_per_known_issues_register_next_poll_succeeded_tick_count_advancing_process_A_123602_process_B_31038_at_14_29_39_41_conservative_override_vix_above_13_or_gap_above_0.5pct_still_false_today_otherwise_eligible_bias_neutral_0pct_new_risk_0_open_positions_clean_slate_capital_109978_realized_9978_bot_alive_TIME_WINDOW_BINDING_NOW_1430_60min_past_1330_no_new_entries_cutoff_1430_FORCE_SQUARE_OFF_NOW_ACTIVE_irrelevant_with_0_positions_59min_before_1530_monthly_nifty_expiry_0dte_gamma_risk_extreme_FORMAL_SKIP_FOR_DAY_FIRM_AND_BINDING_per_1315_plan_no_fresh_entry_today_next_meaningful_action_1515_square_off_no_op_with_0_positions_then_1530_monthly_expiry_then_tomorrow_0825_daily_maintenance_0830_daily_start",
    "market_session": "regular",
    "vix": 10.89,
    "risk_budget_pct": 0,
    "bias_decision": "neutral",
    "macro_in_blackout": False,
    "decision_summary": "14:30 IST FORCE-SQUARE-OFF cron tick per intraday.force_square_off_time. Last decision 14:00 IST (30 min ago) held FORMAL_SKIP_FOR_DAY_FIRM_AND_BINDING. 14:30 is the bot's hard backstop to close all intraday positions per settings.yaml intraday config. With 0 open positions, force-square-off is a NO-OP. Key facts (14:00 -> 14:30, 30 min delta): (a) VIX 10.89 (-0.02 from 14:00s 10.91 - essentially flat calm, 1.0x mult unchanged). (b) candle_regime both still range conf 0.7 (textbook condor day per regime, NIFTY 5d range_pct 0.25% very tight, BNF 0.41% tight per yfinance). (c) 0 open positions unchanged - clean slate. (d) Capital 1,09,978 INR, realized +9,978 INR. (e) No macro blackout (monthly NIFTY expiry 59 min away, but blackout window 60-min before triggers AT 14:30 - exactly NOW, so the bot's blackout logic may also be active; India GDP tomorrow 17:30 = 1619 min away). (f) Bot tick_count advancing on both scanner processes (process A 123602 at 14:29:39, process B 31038 at 14:29:41). (g) Bot log tail at 14:30: 1 transient getaddrinfo failed at 14:28:41 (known self-recover per known-issues register, next poll succeeded). All other entries are skip: intraday mode - no_new_trades_after (13:30) hit on both processes. (h) Path bug NOT seen in 14:30 log tail - 30c0fc9 fix confirmed working. No force-action check failed, no brain-action check failed warnings. Both action channels working as designed. Two persistent blockers unchanged from 14:00: (1) US futures STILL +1.29% > 0.4% threshold - BLOCK state from 13:30:02/56 still in effect. 5h 30m above threshold, no resolution. 09:45 plans contingency FIRM. (2) STILL BINDING: 13:30 no-new-entries cutoff REACHED 60 min ago per intraday.no_new_trades_after. NOW 14:30 FORCE-SQUARE-OFF ACTIVE - bot's main loop will call square_off_all() which is a no-op with 0 positions. Conservative override (VIX>13 OR gap>0.5%) still FALSE - market is otherwise eligible but execution channels + TIME-WINDOW CONSTRAINTS preclude new entry. 15:30 monthly NIFTY expiry is 59 min away. Even if all blockers cleared, no new entry can be placed today. 13:15 FORMAL_SKIP_FOR_DAY_FIRM_AND_BINDING holds at 14:30.",
    "rationale": "14:30 IST FORCE-SQUARE-OFF cron tick per intraday.force_square_off_time. Last decision 14:00 IST (30 min ago) held FORMAL_SKIP_FOR_DAY_FIRM_AND_BINDING. 14:30 is the bot's hard backstop to close all intraday positions per settings.yaml intraday config (force_square_off_time: 14:30). With 0 open positions, force-square-off is a NO-OP. Key facts (14:00 -> 14:30, 30 min delta): (a) VIX 10.89 (-0.02 from 14:00s 10.91 - essentially flat, calm 1.0x mult). (b) candle_regime both still range conf 0.7 (NIFTY 5d range_pct 0.25%, BNF 0.41% per yfinance - both TIGHT range regime). (c) 0 open positions unchanged. (d) No macro blackout in effect yet. (e) Bot tick_count advancing on both scanner processes (123602 + 31038 at 14:29:39/41), both alive, both blocking on 13:30 cutoff. (f) Path bug NOT seen in 14:30 log tail - 30c0fc9 fix confirmed working. 1 transient getaddrinfo failed at 14:28:41 self-recovered (known per known-issues register, next poll at 14:28:42+ succeeded). No force-action check failed, no brain-action check failed warnings. Both action channels working as designed. Two persistent blockers unchanged from 14:00: (1) US futures STILL +1.29% > 0.4% threshold - BLOCK state from 13:30:02/56 still in effect, 5h 30m above threshold, no resolution. 09:45 plans contingency (SKIP entry today entirely if US futures still >0.4%) is FIRM. (2) STILL BINDING: 13:30 no-new-entries cutoff REACHED 60 min ago per intraday.no_new_trades_after - operational constraint blocks new entries independently of US futures BLOCK and 0DTE gamma risk. Conservative override (VIX>13 OR gap>0.5%) still FALSE - market is otherwise eligible. 14:30 FORCE-SQUARE-OFF is NOW ACTIVE (this tick) - the bot's main loop will call square_off_all() which is a no-op with 0 positions. 15:15 square_off will be a no-op too. 15:30 monthly NIFTY expiry is 59 min away. Even if all blockers cleared, no new entry can be placed today. 13:15 FORMAL_SKIP_FOR_DAY_FIRM_AND_BINDING holds at 14:30. No new capital at risk today. No reassessment needed before 15:15 square_off or 15:30 monthly expiry.",
    "risk_budget_reasoning": "Risk budget = 0% new capital for the 14:30 FORCE-SQUARE-OFF cron tick. (a) 14:30 is the next scheduled 5-min cron tick AND the force-square-off moment per intraday config. (b) 13:30 NO-NEW-ENTRIES CUTOFF was REACHED 60 min ago per intraday.no_new_trades_after - bot log confirms skip firing in SCAN loop on both scanner processes. This is the BINDING constraint - no new entries can be placed even if US futures BLOCK clears. (c) US futures STILL +1.29% > 0.4% threshold - BLOCK state from 13:30:02/56 still in effect. 5h 30m above threshold, no resolution. 09:45 plans contingency is FIRM. (d) Path bug NOT seen in 14:30 log tail - 30c0fc9 fix confirmed working. (e) Bot Mavis co-pilot independently BLOCKING on US futures gap. (f) Conservative override (VIX>13 OR gap>0.5%) still FALSE - market is otherwise eligible. (g) Monthly NIFTY expiry 15:30 (59 min) - 0DTE gamma risk now extreme in final hour. (h) 0 open positions, capital 1,09,978 INR, realized +9,978 INR. (i) Bot alive (tick_count ~123,602 + 31,038 at 14:29:39/41, both blocking). (j) 14:30 force-square-off NOW ACTIVE but irrelevant with 0 positions. (k) 1 transient getaddrinfo failed at 14:28:41 self-recovered per known-issues register. No new capital at risk today. 13:15 FORMAL_SKIP_FOR_DAY_FIRM_AND_BINDING holds at 14:30.",
    "candle_regime_evidence": {
        "NIFTY": {
            "confidence": 0.7,
            "regime": "range",
            "reason": "range=0.25% very tight + vix=10.89 low (1.0x mult, -0.02 from 14:00s 10.91 - essentially flat). 5d trend -0.30% (per yfinance, narrower than 14:00s -0.46% - still flat/mild). Live print 24,146.05 yfinance close vs prev close 24,090.85 = +0.23% gap (within 0.5%). Range regime intact. 5d range_pct 0.25% (narrower than 14:00s 0.46% - very TIGHT). Still textbook 0DTE iron condor setup per regime, but (a) US futures BLOCK active, (b) 13:30 no-new-entries cutoff REACHED 60 min ago - BINDING, (c) 0DTE monthly expiry 59min away - gamma risk extreme, (d) 14:30 FORCE-SQUARE-OFF ACTIVE - irrelevant with 0 positions. 13:15 FORMAL_SKIP_FIRM_AND_BINDING holds at 14:30 - no new entry today.",
            "range_pct": 0.25,
            "last_close": 24146.05078125,
            "trend_5d": "flat",
            "change_5d_pct": -0.3
        },
        "BANKNIFTY": {
            "confidence": 0.7,
            "regime": "range",
            "reason": "range=0.41% tight + vix=10.89 low (1.0x mult). 5d trend -0.12% (very flat, narrower than 14:00s -0.23%). Live print 57,454.55 yfinance close vs prev close 57,509.95 = -0.10% gap (within 0.5%). BNF unchanged from 14:00 in regime terms. Range regime intact. 5d range_pct 0.41% (narrower than 14:00s 0.58% - very TIGHT). Still textbook 0DTE iron condor setup per regime, but execution channels closed + TIME-WINDOW CONSTRAINTS (13:30 cutoff REACHED 60 min ago + 14:30 FORCE-SQUARE-OFF ACTIVE) now BINDING preclude new entry. 13:15 FORMAL_SKIP_FIRM_AND_BINDING holds at 14:30 - no new entry today.",
            "range_pct": 0.41,
            "last_close": 57454.55078125,
            "trend_5d": "flat",
            "change_5d_pct": -0.12
        }
    },
    "macro_evidence": {
        "upcoming": [
            {
                "importance": 2,
                "minutes_away": 59,
                "name": "monthly_expiry_NIFTY",
                "datetime_ist": "2026-08-28 15:30"
            },
            {
                "importance": 2,
                "minutes_away": 1619,
                "name": "india_gdp",
                "datetime_ist": "2026-08-29 17:30"
            }
        ],
        "in_blackout": False,
        "interpretation": "No near-term event risk in the 60-min blackout window AT 14:30 (the 60-min window for monthly expiry starts at 14:30, so we are exactly on the boundary - some implementations trigger at <=60 min, some at <60 min. The bot's macro.in_blackout flag reads false in the live state). Monthly NIFTY expiry 59 min away at 15:30 (0DTE) - elevated gamma/vol risk in the last hour, near the boundary of macro blackout. India GDP tomorrow 17:30, well outside window. Macro is QUIET. The 13:30 no-new-entries cutoff is a separate operational constraint (not a macro event) - was REACHED 60 min ago, still BINDING. The 14:30 force-square-off is NOW ACTIVE (this tick) - another operational constraint. US futures +1.29% > 0.4% threshold is a separate cautious overlay from the bot Mavis co-pilot (not macro calendar) - this is the condition that has driven the SKIP-for-day decision. No material change in macro from 14:00 except clock advancing 30 min. 13:15 FORMAL_SKIP_FIRM_AND_BINDING holds at 14:30 - no new event, no new blackout, no reassessment warranted before 15:15 square_off or 15:30 monthly expiry."
    },
    "research_evidence": {
        "available": False,
        "fallback": "Research PDF download still failing (kotak_research.download_latest_research_pdf:52 WARNING at 14:30 - could not find derivatives PDF URL). Candle+macro+VIX-only mode. VIX 10.89 (calm, 1.0x multiplier, -0.02 from 14:00s 10.91 - essentially flat). Bot Mavis co-pilot is blocking on US futures +1.29% > 0.4% threshold - BLOCK state from 13:30:02/56 still in effect. 13:30 no-new-entries cutoff was REACHED 60 min ago - this is the BINDING constraint that prevents new entry even if US futures clears. 14:30 FORCE-SQUARE-OFF NOW ACTIVE - irrelevant with 0 positions. Even if US futures reversed now, the 13:30 cutoff is REACHED and 0DTE monthly expiry 59min away - poor risk/reward for fresh entry. SKIP for today, FIRM AND BINDING at 14:30."
    },
    "open_positions_summary": {
        "note": "0 open positions (clean slate, unchanged since 09:46 IST 2026-08-27 EOD square-off). Capital 1,09,978 INR, realized +9,978 INR for the run-to-date. Today: monthly NIFTY expiry at 15:30 (59 min) - 0DTE structures with extreme gamma risk in last hour. Regular session 5h 30m in. US futures STILL +1.29% > 0.4% threshold - bot Mavis co-pilot STILL BLOCKING entries (BLOCK state from 13:30:02/56 still in effect). Path bug NOT seen in 14:30 log tail - 30c0fc9 fix confirmed working. 1 transient getaddrinfo failed at 14:28:41 self-recovered per known-issues register. 13:15/13:20/13:25/13:30/13:35/13:40/13:45/13:50/14:00 FORMAL_SKIP_FIRM_FOR_DAY is FIRM AND BINDING at 14:30 - 13:30 no-new-entries cutoff REACHED 60 min ago per intraday config. 14:30 FORCE-SQUARE-OFF NOW ACTIVE - irrelevant with 0 positions. Even if both blockers cleared, no new entry can be placed after 13:30. 0DTE gamma risk extreme. No fresh entry today. Next meaningful action: 15:15 square_off (no-op with 0 positions), 15:30 monthly expiry, then tomorrow 08:25 daily-maintenance + 08:30 daily-start. Bot alive (tick_count ~123,602 + 31,038 at 14:29:39/41, both blocking).",
        "details": [],
        "max_reached": False,
        "count": 0,
        "max_positions_limit": 2
    },
    "tick_context": {
        "previous_decision_ist": "2026-08-28 14:00:00",
        "previous_decision_bias": "neutral",
        "previous_decision_actions_count": 0,
        "decision_changed": False,
        "decision_change_reason": "14:30 IST FORCE-SQUARE-OFF cron tick - same call as 13:15/13:20/13:25/13:30/13:35/13:40/13:45/13:50/14:00 (HOLD, bias=neutral, 0% new risk, 0 actions). The 14:30 force-square-off is a bot-level action (square_off_all in the main loop), not a brain action. With 0 open positions, force-square-off is a NO-OP. The brain just confirms HOLD/0 positions. All blockers unchanged: US futures STILL +1.29% > 0.4% threshold (BLOCK state from 13:30:02/56 still in effect, 5h 30m above threshold), 13:30 no-new-entries cutoff REACHED 60 min ago (still BINDING), 14:30 FORCE-SQUARE-OFF NOW ACTIVE (irrelevant with 0 positions), Path bug still not seen in live bot (30c0fc9 fix confirmed working). 1 transient getaddrinfo failed at 14:28:41 self-recovered per known-issues register. Conservative override (VIX>13 OR gap>0.5%) still FALSE. 13:15 FORMAL_SKIP_FIRM_AND_BINDING holds at 14:30 - same call, fresh tick, no new info, no new actions, no new risk.",
        "key_change_since_previous": "30 min later (14:00 -> 14:30). VIX 10.89 (-0.02 from 14:00s 10.91, essentially flat - 1.0x mult unchanged). candle_regime both still range conf 0.7 (textbook condor day per regime). 0 open positions unchanged. No macro change. market_session still regular. Bot tick_count advancing on both processes: process A scanned cycles 10000/10006/10012/10018 (14:28:57 to 14:30:28), process B scanned cycles 997/1003/1009/1015 (14:29:02 to 14:30:32). LiveKotak heartbeats: process A 14:29:39 tick_count=123602, process B 14:29:41 tick_count=31038. 1 transient getaddrinfo failed at 14:28:41 (kotak_prod_feed._poll_loop:606 URLError: getaddrinfo failed) - known self-recover per known-issues register, next poll at 14:28:57 succeeded. 13:30 NO-NEW-ENTRIES CUTOFF REACHED 60 min ago - bot SCAN log still shows skip: intraday mode - no_new_trades_after (13:30) hit on both processes. 14:30 FORCE-SQUARE-OFF NOW ACTIVE (this tick) - bot's main loop will call square_off_all() which is a no-op with 0 positions. 09:45 plans contingency FIRM since 10:00, reconfirmed at 10:15, observation-only at 10:20/10:25, recovery at 13:15, nochange at 13:20/13:25, FIRM AND BINDING at 13:30, holds at 13:35/13:40/13:45/13:50/14:00, holds at 14:30. 11:30 US cash open did NOT resolve. Bot Mavis co-pilot independently BLOCKING on US futures. 15:15 square_off in 45 min, 15:30 monthly expiry in 59 min. Even if all blockers cleared, no new entry today. 13:15 FORMAL_SKIP_FIRM_AND_BINDING holds at 14:30.",
        "log_tail_evidence_intraday_cutoff_active": "2026-08-28 14:28:41.862 | INFO | kotak_bot.data.live_feed:_live_kotak_loop:437 | LiveKotak heartbeat: authed=True subscribed=40 latest=40 tick_count=30400 | 2026-08-28 14:28:57.941 | INFO | __main__:run_paper:1231 | [SCAN] cycle=10000 | skip: intraday mode - no_new_trades_after (13:30) hit | 2026-08-28 14:29:02.031 | INFO | __main__:run_paper:1238 | [SCAN] cycle=997 | skip: intraday mode - no_new_trades_after (13:30) hit | 2026-08-28 14:29:27.957 | INFO | __main__:run_paper:1231 | [SCAN] cycle=10006 | skip: intraday mode - no_new_trades_after (13:30) hit | 2026-08-28 14:29:32.065 | INFO | __main__:run_paper:1238 | [SCAN] cycle=1003 | skip: intraday mode - no_new_trades_after (13:30) hit | 2026-08-28 14:29:39.950 | INFO | kotak_bot.data.live_feed:_live_kotak_loop:437 | LiveKotak heartbeat: authed=True subscribed=48 latest=48 tick_count=123602 | 2026-08-28 14:29:41.877 | INFO | kotak_bot.data.live_feed:_live_kotak_loop:437 | LiveKotak heartbeat: authed=True subscribed=40 latest=40 tick_count=31038 | 2026-08-28 14:29:58.026 | INFO | __main__:run_paper:1231 | [SCAN] cycle=10012 | skip: intraday mode - no_new_trades_after (13:30) hit | 2026-08-28 14:30:02.086 | INFO | __main__:run_paper:1238 | [SCAN] cycle=1009 | skip: intraday mode - no_new_trades_after (13:30) hit | 2026-08-28 14:30:28.081 | INFO | __main__:run_paper:1231 | [SCAN] cycle=10018 | skip: intraday mode - no_new_trades_after (13:30) hit | 2026-08-28 14:30:32.186 | INFO | __main__:run_paper:1238 | [SCAN] cycle=1015 | skip: intraday mode - no_new_trades_after (13:30) hit. Bot log tail at 14:30 is CLEAN except 1 transient getaddrinfo failed at 14:28:41 (self-recovered per known-issues register, next poll succeeded). All SCAN entries are skip: intraday mode - no_new_trades_after (13:30) hit on both scanner processes. LiveKotak heartbeat firing every ~30s on both processes. No force-action check failed, no brain-action check failed warnings. Both action channels working as designed. Path bug NOT seen in 14:30 log tail - 30c0fc9 fix confirmed working."
    },
    "actions_count": 0
}

# Archive the previous last_decision to history (per the pattern seen in the file)
prev = data["last_decision"]
archived = {
    "ts": prev.get("ts"),
    "timestamp": prev.get("timestamp"),
    "ist_time": prev.get("ist_time"),
    "bias": prev.get("bias"),
    "actions": prev.get("actions", []),
    "actions_count": prev.get("actions_count", 0),
    "note": prev.get("note", ""),
    "archived_from": "last_decision",
    "archived_at": "2026-08-28 14:30:36"
}
data["history"].insert(0, archived)

# Set the new last_decision
data["last_decision"] = new_decision

# Write back with json.dump
out = json.dumps(data, indent=2, ensure_ascii=False)
p.write_text(out, encoding="utf-8")

# Verify: re-parse the file
verify = json.loads(p.read_text(encoding="utf-8-sig"))
print(f"OK: new last_decision.ist_time = {verify['last_decision']['ist_time']}", flush=True)
print(f"OK: new call_count_today = {verify['call_count_today']}", flush=True)
print(f"OK: new top-level timestamp = {verify['timestamp']}", flush=True)
print(f"OK: history entries now = {len(verify['history'])}", flush=True)
print(f"OK: history[0].ist_time = {verify['history'][0]['ist_time']} (should be {prev.get('ist_time')})", flush=True)
print(f"OK: bias = {verify['last_decision']['bias']}", flush=True)
print(f"OK: actions_count = {verify['last_decision']['actions_count']}", flush=True)
print(f"OK: vix = {verify['last_decision']['vix']}", flush=True)
