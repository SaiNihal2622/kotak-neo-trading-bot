"""One-shot update for trader-desk 14:35 IST 2026-08-28 cron tick.

Writes brain_actions.json (dec) and brain_state.json (last_decision + history)
using the load->mutate->dump pattern (per memory rule 2026-08-28 14:30).
"""
import json
import re
from pathlib import Path
from datetime import datetime, timezone, timedelta

PROJECT = Path(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot")
BRAIN_ACTIONS = PROJECT / "data_cache" / "brain_actions.json"
BRAIN_STATE = PROJECT / "data_cache" / "brain_state.json"

# 14:35 IST 2026-08-28 cron tick
IST = timezone(timedelta(hours=5, minutes=30))
now_ist = datetime(2026, 8, 28, 14, 35, 23, tzinfo=IST)
now_utc = now_ist.astimezone(timezone.utc)

ist_str = now_ist.strftime("%Y-%m-%d %H:%M:%S")
utc_iso = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

# Build the note (matches the pattern from the last 17 ticks)
note = (
    "regular_1435_5min_nochange_observation_FORMAL_SKIP_FIRM_BINDS_holds_"
    "vix_10.84_calm_1.0x_minus_0.05_from_1430s_10.89_essentially_flat_"
    "nifty_24090.85_yfinance_close_vs_prev_close_24090.85_gap_0.0pct_within_0.5pct_"
    "bnf_57509.95_yfinance_close_vs_prev_close_57509.95_gap_0.0pct_within_0.5pct_"
    "5d_range_pct_nifty_0.86pct_bnf_0.87pct_tight_range_"
    "5d_trend_nifty_down_minus_0.66pct_bnf_flat_minus_0.44pct_"
    "candle_regime_both_range_conf_0.7_textbook_condor_day_per_regime_"
    "macro_no_blackout_monthly_nifty_expiry_54min_at_15_30_0dte_gamma_risk_extreme_in_final_hour_"
    "india_gdp_tomorrow_1614min_"
    "us_futures_still_plus_1.29pct_above_0.4pct_threshold_no_resolution_5h35m_above_threshold_"
    "path_bug_NOT_seen_in_1435_log_tail_30c0fc9_fix_confirmed_working_"
    "bot_log_tail_clean_all_skips_per_1330_intraday_cutoff_both_scanner_processes_blocking_"
    "tick_count_advancing_process_A_128114_process_B_33960_at_14_34_40_42_"
    "conservative_override_vix_above_13_or_gap_above_0.5pct_still_false_today_otherwise_eligible_"
    "bias_neutral_0pct_new_risk_0_open_positions_clean_slate_capital_109978_realized_9978_bot_alive_"
    "TIME_WINDOW_BINDING_NOW_1435_65min_past_1330_no_new_entries_cutoff_"
    "5min_into_1430_force_square_off_window_40min_before_1515_square_off_"
    "54min_before_1530_monthly_nifty_expiry_0dte_gamma_risk_extreme_"
    "FORMAL_SKIP_FOR_DAY_FIRM_AND_BINDING_per_1315_plan_no_fresh_entry_today_"
    "no_reassessment_needed_next_meaningful_action_1515_square_off_no_op_with_0_positions_"
    "then_1530_monthly_expiry_then_tomorrow_0825_daily_maintenance_0830_daily_start"
)

rationale = (
    "14:35 IST 5-min nochange observation tick - same call as 14:00 and 14:30. "
    "VIX 10.84 (-0.05 from 14:30s 10.89 - essentially flat calm, 1.0x mult unchanged). "
    "candle_regime both still range conf 0.7 (NIFTY 5d range_pct 0.86%, BNF 0.87% per yfinance - tight range regime, textbook 0DTE condor day per regime). "
    "0 open positions unchanged. No macro blackout (monthly NIFTY expiry 54 min away, but blackout window starts at 14:30 - now active; bot's macro.in_blackout flag still reads false in live state). "
    "Bot tick_count advancing on both scanner processes (process A 128114 at 14:34:40, process B 33960 at 14:34:42), both alive, both blocking on 13:30 cutoff. "
    "Bot log tail at 14:35 CLEAN: all SCAN entries are skip: intraday mode - no_new_trades_after (13:30) hit on both processes. "
    "Path bug NOT seen in 14:35 log tail - 30c0fc9 fix confirmed working. No force-action check failed, no brain-action check failed warnings. Both action channels working as designed. "
    "Two persistent blockers unchanged from 14:30: "
    "(1) US futures STILL +1.29% > 0.4% threshold - BLOCK state from 13:30:02/56 still in effect, 5h 35m above threshold, no resolution. 09:45 plans contingency FIRM. "
    "(2) STILL BINDING: 13:30 no-new-entries cutoff REACHED 65 min ago per intraday.no_new_trades_after. "
    "14:30 FORCE-SQUARE-OFF ACTIVE for 5 min (this tick) - bot's main loop called square_off_all() which is a no-op with 0 positions. "
    "Conservative override (VIX>13 OR gap>0.5%) still FALSE - market is otherwise eligible. "
    "Even if all blockers cleared, no new entry can be placed after 13:30 today. 0DTE monthly expiry 54 min away - gamma risk extreme in final hour. "
    "15:15 square_off in 40 min (no-op with 0 positions), 15:30 monthly expiry in 54 min. "
    "13:15 FORMAL_SKIP_FIRM_AND_BINDING holds at 14:35. No new capital at risk today. No reassessment needed before 15:15 square_off or 15:30 monthly expiry."
)

risk_budget_reasoning = (
    "Risk budget = 0% new capital for the 14:35 5-min nochange observation cron tick. "
    "(a) 13:30 NO-NEW-ENTRIES CUTOFF was REACHED 65 min ago per intraday.no_new_trades_after - bot log confirms skip firing in SCAN loop on both scanner processes. This is the BINDING constraint. "
    "(b) US futures STILL +1.29% > 0.4% threshold - BLOCK state from 13:30:02/56 still in effect. 5h 35m above threshold, no resolution. 09:45 plans contingency is FIRM. "
    "(c) Path bug NOT seen in 14:35 log tail - 30c0fc9 fix confirmed working. "
    "(d) Bot Mavis co-pilot independently BLOCKING on US futures gap. "
    "(e) Conservative override (VIX>13 OR gap>0.5%) still FALSE - market is otherwise eligible. "
    "(f) Monthly NIFTY expiry 15:30 (54 min) - 0DTE gamma risk now extreme in final hour. "
    "(g) 0 open positions, capital 1,09,978 INR, realized +9,978 INR. "
    "(h) Bot alive (tick_count 128,114 + 33,960 at 14:34:40/42, both blocking). "
    "(i) 14:30 force-square-off ACTIVE for 5 min - irrelevant with 0 positions. "
    "(j) Bot log tail CLEAN. No new capital at risk today. 13:15 FORMAL_SKIP_FIRM_AND_BINDING holds at 14:35."
)

decision_summary = (
    "14:35 IST 5-min nochange observation tick (5 min after 14:30 FORCE-SQUARE-OFF). "
    "VIX 10.84 (calm, 1.0x mult, -0.05 from 14:30s 10.89 - essentially flat). "
    "candle_regime both still range conf 0.7 (NIFTY 5d range_pct 0.86%, BNF 0.87% per yfinance - tight range). "
    "0 open positions unchanged. No macro blackout. "
    "Bot tick_count advancing on both scanner processes (128,114 + 33,960 at 14:34:40/42), both alive, both blocking on 13:30 cutoff. "
    "Bot log tail CLEAN: all SCAN entries are skip: intraday mode - no_new_trades_after (13:30) hit. "
    "Path bug NOT seen - 30c0fc9 fix confirmed working. Both action channels working. "
    "Two persistent blockers unchanged: "
    "(1) US futures STILL +1.29% > 0.4% threshold - BLOCK state from 13:30:02/56 still in effect, 5h 35m above threshold, no resolution. "
    "(2) 13:30 no-new-entries cutoff REACHED 65 min ago - BINDING. "
    "14:30 force-square-off ACTIVE for 5 min (this tick) - no-op with 0 positions. "
    "Conservative override (VIX>13 OR gap>0.5%) still FALSE. 0DTE monthly expiry 54 min away - gamma risk extreme. "
    "13:15 FORMAL_SKIP_FIRM_AND_BINDING holds at 14:35 - no new entry today. "
    "Next meaningful action: 15:15 square_off (no-op), 15:30 monthly expiry, then tomorrow 08:25 daily-maintenance + 08:30 daily-start."
)

candle_regime_evidence = {
    "NIFTY": {
        "confidence": 0.7,
        "regime": "range",
        "reason": (
            "range=0.86% tight + vix=10.84 low (1.0x mult, -0.05 from 14:30s 10.89 - essentially flat). "
            "5d trend -0.66% (per yfinance - same as 14:30, mild down). "
            "Live print 24,090.85 yfinance close vs prev close 24,090.85 = 0.0% gap (within 0.5%). "
            "Range regime intact. 5d range_pct 0.86% (same as 14:30 - tight). "
            "Still textbook 0DTE iron condor setup per regime, but (a) US futures BLOCK active, "
            "(b) 13:30 no-new-entries cutoff REACHED 65 min ago - BINDING, "
            "(c) 0DTE monthly expiry 54min away - gamma risk extreme, "
            "(d) 14:30 FORCE-SQUARE-OFF ACTIVE - irrelevant with 0 positions. "
            "13:15 FORMAL_SKIP_FIRM_AND_BINDING holds at 14:35 - no new entry today."
        ),
        "range_pct": 0.86,
        "last_close": 24090.85,
        "trend_5d": "down",
        "change_5d_pct": -0.66,
    },
    "BANKNIFTY": {
        "confidence": 0.7,
        "regime": "range",
        "reason": (
            "range=0.87% tight + vix=10.84 low (1.0x mult, -0.05 from 14:30s 10.89 - essentially flat). "
            "5d trend -0.44% (per yfinance - same as 14:30, very flat/mild). "
            "Live print 57,509.95 yfinance close vs prev close 57,509.95 = 0.0% gap (within 0.5%). "
            "BNF unchanged from 14:30 in regime terms. Range regime intact. "
            "5d range_pct 0.87% (same as 14:30 - tight). "
            "Still textbook 0DTE iron condor setup per regime, but execution channels closed + "
            "TIME-WINDOW CONSTRAINTS (13:30 cutoff REACHED 65 min ago + 14:30 FORCE-SQUARE-OFF ACTIVE) "
            "now BINDING preclude new entry. 13:15 FORMAL_SKIP_FIRM_AND_BINDING holds at 14:35 - no new entry today."
        ),
        "range_pct": 0.87,
        "last_close": 57509.95,
        "trend_5d": "flat",
        "change_5d_pct": -0.44,
    },
}

macro_evidence = {
    "upcoming": [
        {
            "importance": 2,
            "minutes_away": 54,
            "name": "monthly_expiry_NIFTY",
            "datetime_ist": "2026-08-28 15:30",
        },
        {
            "importance": 2,
            "minutes_away": 1614,
            "name": "india_gdp",
            "datetime_ist": "2026-08-29 17:30",
        },
    ],
    "in_blackout": False,
    "interpretation": (
        "No near-term event risk in the 60-min blackout window AT 14:35 (the 60-min window for monthly expiry started at 14:30, "
        "so we are 5 min INTO the window - the bot's macro.in_blackout flag still reads false in the live state, "
        "but for a manual trader this would now be a hard block). "
        "Monthly NIFTY expiry 54 min away at 15:30 (0DTE) - elevated gamma/vol risk in the last hour. "
        "India GDP tomorrow 17:30, well outside window. "
        "Macro is QUIET in absolute terms. "
        "The 13:30 no-new-entries cutoff is a separate operational constraint (not a macro event) - was REACHED 65 min ago, still BINDING. "
        "The 14:30 force-square-off is ACTIVE (this tick is 5 min into it) - another operational constraint. "
        "US futures +1.29% > 0.4% threshold is a separate cautious overlay from the bot Mavis co-pilot (not macro calendar) - "
        "this is the condition that has driven the SKIP-for-day decision. "
        "No material change in macro from 14:30 except clock advancing 5 min. "
        "13:15 FORMAL_SKIP_FIRM_AND_BINDING holds at 14:35 - no new event, no new blackout, no reassessment warranted before 15:15 square_off or 15:30 monthly expiry."
    ),
}

research_evidence = {
    "available": False,
    "fallback": (
        "Research PDF download still failing (kotak_research.download_latest_research_pdf:52 WARNING at 14:35 - could not find derivatives PDF URL). "
        "Candle+macro+VIX-only mode. VIX 10.84 (calm, 1.0x multiplier, -0.05 from 14:30s 10.89 - essentially flat). "
        "Bot Mavis co-pilot is blocking on US futures +1.29% > 0.4% threshold - BLOCK state from 13:30:02/56 still in effect. "
        "13:30 no-new-entries cutoff was REACHED 65 min ago - this is the BINDING constraint that prevents new entry even if US futures clears. "
        "14:30 FORCE-SQUARE-OFF ACTIVE for 5 min (this tick) - no-op with 0 positions. "
        "Even if US futures reversed now, the 13:30 cutoff is REACHED and 0DTE monthly expiry 54min away - poor risk/reward for fresh entry. "
        "SKIP for today, FIRM AND BINDING at 14:35."
    ),
}

open_positions_summary = {
    "note": (
        "0 open positions (clean slate, unchanged since 09:46 IST 2026-08-27 EOD square-off). "
        "Capital 1,09,978 INR, realized +9,978 INR for the run-to-date. "
        "Today: monthly NIFTY expiry at 15:30 (54 min) - 0DTE structures with extreme gamma risk in last hour. "
        "Regular session 6h 5m in. US futures STILL +1.29% > 0.4% threshold - bot Mavis co-pilot STILL BLOCKING entries "
        "(BLOCK state from 13:30:02/56 still in effect). "
        "Path bug NOT seen in 14:35 log tail - 30c0fc9 fix confirmed working. "
        "Bot log tail CLEAN: all SCAN entries are skip: intraday mode - no_new_trades_after (13:30) hit on both scanner processes. "
        "13:15/13:20/13:25/13:30/13:35/13:40/13:45/13:50/14:00/14:30 FORMAL_SKIP_FIRM_FOR_DAY is FIRM AND BINDING at 14:35 - "
        "13:30 no-new-entries cutoff REACHED 65 min ago per intraday config. "
        "14:30 FORCE-SQUARE-OFF ACTIVE for 5 min (this tick) - irrelevant with 0 positions. "
        "Even if both blockers cleared, no new entry can be placed after 13:30. 0DTE gamma risk extreme. No fresh entry today. "
        "Next meaningful action: 15:15 square_off (no-op with 0 positions), 15:30 monthly expiry, then tomorrow 08:25 daily-maintenance + 08:30 daily-start. "
        "Bot alive (tick_count 128,114 + 33,960 at 14:34:40/42, both blocking)."
    ),
    "details": [],
    "max_reached": False,
    "count": 0,
    "max_positions_limit": 2,
}

tick_context = {
    "previous_decision_ist": "2026-08-28 14:30:36",
    "previous_decision_bias": "neutral",
    "previous_decision_actions_count": 0,
    "decision_changed": False,
    "decision_change_reason": (
        "14:35 IST 5-min nochange observation cron tick - same call as 14:00/14:30 (HOLD, bias=neutral, 0% new risk, 0 actions). "
        "The 14:30 force-square-off is a bot-level action (square_off_all in the main loop), not a brain action. "
        "With 0 open positions, force-square-off is a NO-OP. The brain just confirms HOLD/0 positions. "
        "All blockers unchanged: US futures STILL +1.29% > 0.4% threshold (BLOCK state from 13:30:02/56 still in effect, 5h 35m above threshold), "
        "13:30 no-new-entries cutoff REACHED 65 min ago (still BINDING), "
        "14:30 FORCE-SQUARE-OFF ACTIVE for 5 min (this tick) - irrelevant with 0 positions, "
        "Path bug still not seen in live bot (30c0fc9 fix confirmed working). "
        "Bot log tail CLEAN: all SCAN entries are skip: intraday mode - no_new_trades_after (13:30) hit on both processes. "
        "Conservative override (VIX>13 OR gap>0.5%) still FALSE. "
        "13:15 FORMAL_SKIP_FIRM_AND_BINDING holds at 14:35 - same call, fresh tick, no new info, no new actions, no new risk."
    ),
    "key_change_since_previous": (
        "5 min later (14:30 -> 14:35). VIX 10.84 (-0.05 from 14:30s 10.89, essentially flat - 1.0x mult unchanged). "
        "candle_regime both still range conf 0.7 (textbook condor day per regime). "
        "0 open positions unchanged. No macro change. market_session still regular. "
        "Bot tick_count advancing on both processes: process A heartbeat 14:34:40 tick_count=128114, process B heartbeat 14:34:42 tick_count=33960. "
        "LiveKotak heartbeats firing every ~30s on both processes. "
        "Bot log tail CLEAN: all SCAN entries are skip: intraday mode - no_new_trades_after (13:30) hit on both processes. "
        "13:30 NO-NEW-ENTRIES CUTOFF REACHED 65 min ago - bot SCAN log still shows skip firing in SCAN loop on both scanner processes. "
        "14:30 FORCE-SQUARE-OFF ACTIVE for 5 min (this tick) - bot's main loop called square_off_all() which is a no-op with 0 positions. "
        "09:45 plans contingency FIRM since 10:00, reconfirmed at 10:15, observation-only at 10:20/10:25, recovery at 13:15, "
        "nochange at 13:20/13:25, FIRM AND BINDING at 13:30, holds at 13:35/13:40/13:45/13:50/14:00, holds at 14:30, holds at 14:35. "
        "11:30 US cash open did NOT resolve. Bot Mavis co-pilot independently BLOCKING on US futures. "
        "15:15 square_off in 40 min, 15:30 monthly expiry in 54 min. Even if all blockers cleared, no new entry today. "
        "13:15 FORMAL_SKIP_FIRM_AND_BINDING holds at 14:35."
    ),
    "log_tail_evidence_intraday_cutoff_active": (
        "2026-08-28 14:32:42.143 | INFO | LiveKotak heartbeat: authed=True subscribed=40 latest=40 tick_count=32760 | "
        "2026-08-28 14:32:59.138 | INFO | __main__:run_paper:1231 | [SCAN] cycle=10048 | skip: intraday mode - no_new_trades_after (13:30) hit | "
        "2026-08-28 14:33:03.305 | INFO | __main__:run_paper:1238 | [SCAN] cycle=1045 | skip: intraday mode - no_new_trades_after (13:30) hit | "
        "2026-08-28 14:33:29.160 | INFO | __main__:run_paper:1231 | [SCAN] cycle=10054 | skip: intraday mode - no_new_trades_after (13:30) hit | "
        "2026-08-28 14:33:33.319 | INFO | __main__:run_paper:1238 | [SCAN] cycle=1051 | skip: intraday mode - no_new_trades_after (13:30) hit | "
        "2026-08-28 14:33:40.111 | INFO | LiveKotak heartbeat: authed=True subscribed=48 latest=48 tick_count=127159 | "
        "2026-08-28 14:33:42.209 | INFO | LiveKotak heartbeat: authed=True subscribed=40 latest=40 tick_count=33360 | "
        "2026-08-28 14:33:59.184 | INFO | __main__:run_paper:1231 | [SCAN] cycle=10060 | skip: intraday mode - no_new_trades_after (13:30) hit | "
        "2026-08-28 14:34:03.371 | INFO | __main__:run_paper:1238 | [SCAN] cycle=1057 | skip: intraday mode - no_new_trades_after (13:30) hit | "
        "2026-08-28 14:34:29.233 | INFO | __main__:run_paper:1231 | [SCAN] cycle=10066 | skip: intraday mode - no_new_trades_after (13:30) hit | "
        "2026-08-28 14:34:33.411 | INFO | __main__:run_paper:1238 | [SCAN] cycle=1063 | skip: intraday mode - no_new_trades_after (13:30) hit | "
        "2026-08-28 14:34:40.126 | INFO | LiveKotak heartbeat: authed=True subscribed=48 latest=48 tick_count=128114 | "
        "2026-08-28 14:34:42.225 | INFO | LiveKotak heartbeat: authed=True subscribed=40 latest=40 tick_count=33960 | "
        "2026-08-28 14:34:59.286 | INFO | __main__:run_paper:1231 | [SCAN] cycle=10072 | skip: intraday mode - no_new_trades_after (13:30) hit | "
        "2026-08-28 14:35:03.428 | INFO | __main__:run_paper:1238 | [SCAN] cycle=1069 | skip: intraday mode - no_new_trades_after (13:30) hit. "
        "Bot log tail at 14:35 is CLEAN. All SCAN entries are skip: intraday mode - no_new_trades_after (13:30) hit on both scanner processes. "
        "LiveKotak heartbeat firing every ~30s on both processes. No force-action check failed, no brain-action check failed warnings. "
        "Both action channels working as designed. Path bug NOT seen in 14:35 log tail - 30c0fc9 fix confirmed working."
    ),
}

new_decision = {
    "ts": utc_iso,
    "timestamp": utc_iso,
    "ist_time": ist_str,
    "bias": "neutral",
    "source": "mavis",
    "max_positions": 0,
    "actions": [],
    "note": note,
    "market_session": "regular",
    "vix": 10.84,
    "risk_budget_pct": 0,
    "bias_decision": "neutral",
    "macro_in_blackout": False,
    "decision_summary": decision_summary,
    "rationale": rationale,
    "risk_budget_reasoning": risk_budget_reasoning,
    "candle_regime_evidence": candle_regime_evidence,
    "macro_evidence": macro_evidence,
    "research_evidence": research_evidence,
    "open_positions_summary": open_positions_summary,
    "tick_context": tick_context,
    "actions_count": 0,
}

# ----- brain_actions.json (overwrite) -----
brain_actions_doc = {
    "ts": utc_iso,
    "ist_time": ist_str,
    "bias": "neutral",
    "source": "mavis",
    "max_positions": 0,
    "actions": [],
    "note": note,
}
BRAIN_ACTIONS.write_text(
    json.dumps(brain_actions_doc, indent=2, ensure_ascii=False),
    encoding="utf-8",
)
print(f"OK wrote brain_actions.json (size={BRAIN_ACTIONS.stat().st_size}B)")

# ----- brain_state.json (load -> mutate -> dump) -----
data = json.loads(BRAIN_STATE.read_text(encoding="utf-8-sig"))
print(f"OK loaded brain_state.json (history len before={len(data.get('history', []))})")

# Archive previous last_decision (if any) at index 0
prev = data.get("last_decision")
if prev:
    prev_ts = prev.get("ist_time", ist_str)
    archived = dict(prev)
    archived["archived_from"] = "last_decision"
    archived["archived_at"] = ist_str
    archived.setdefault("ist_time", prev_ts)
    data.setdefault("history", []).insert(0, archived)

# Mutate
data["last_decision"] = new_decision
data["call_count_today"] = int(data.get("call_count_today", 0)) + 1
data["timestamp"] = utc_iso
# Keep top-level "today_date" if present
data["today_date"] = data.get("today_date", "2026-08-28")

# Write back
BRAIN_STATE.write_text(
    json.dumps(data, indent=2, ensure_ascii=False),
    encoding="utf-8",
)
print(
    f"OK wrote brain_state.json "
    f"(history len after={len(data['history'])}, call_count_today={data['call_count_today']})"
)

# ----- Sanity checks -----
re = json.loads(BRAIN_STATE.read_text(encoding="utf-8-sig"))
assert re["last_decision"]["bias"] == "neutral"
assert re["last_decision"]["actions"] == []
assert re["last_decision"]["risk_budget_pct"] == 0
assert re["last_decision"]["ist_time"] == ist_str
assert len(re["history"]) == len(data["history"])
print(f"OK sanity checks: bias=neutral, actions=0, risk=0%, history={len(re['history'])} entries")
print(f"OK archived previous last_decision: ist={re['history'][0].get('ist_time')}")
print(f"OK call_count_today incremented to {re['call_count_today']}")
print(f"OK last_decision.ist_time = {re['last_decision']['ist_time']}")
