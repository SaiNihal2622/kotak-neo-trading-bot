"""One-shot to update last_decision narrative fields for the 13:50 cron tick.
Memory rule: never include `"history": [` in new_string (file already has one).
Verify with json.load before declaring fixed.
"""
import json
from pathlib import Path

P = Path(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json")

with P.open("r", encoding="utf-8") as f:
    raw = f.read()

d = json.loads(raw)
ld = d["last_decision"]

# Update the narrative fields for 13:50 tick
ld["decision_summary"] = (
    "13:50 IST 5-min nochange observation tick per the standard cron schedule. "
    "Last decision 13:45:00 IST (5 min ago) was a nochange observation tick that held "
    "FORMAL_SKIP_FOR_DAY_FIRM_AND_BINDING established at 13:30 (when 13:30 no-new-entries cutoff REACHED). "
    "13:50 is the next scheduled 5-min cron tick. "
    "Key facts (13:45 -> 13:50, 5 min delta): "
    "(a) VIX 10.81 (+0.08 from 13:45s 10.73 - essentially flat, calm 1.0x mult unchanged). "
    "(b) candle_regime both still range conf 0.7 (textbook condor day per regime). "
    "(c) 0 open positions unchanged. "
    "(d) Capital 1,09,978 INR, realized +9,978 INR. "
    "(e) No macro blackout (monthly NIFTY expiry 99 min away, not yet in 60-min blackout window; "
    "India GDP tomorrow 17:30 = 1659 min away). "
    "(f) Bot tick_count advancing on both scanner processes (process A scanned cycles 9514/9520/9526/9532/9538, "
    "process B scanned cycles 511/517/523/529/535 per 13:48-13:50 log tail). "
    "(g) Bot log tail at 13:50: all entries are 'skip: intraday mode - no_new_trades_after (13:30) hit' for both "
    "scanner processes. LiveKotak heartbeats firing every ~30s on both processes "
    "(latest tick_count 111,170 + 22,895 at 13:49:39/41). "
    "(h) Path bug NOT seen in 13:50 log tail - 30c0fc9 fix confirmed working. "
    "No force-action check failed, no brain-action check failed warnings. "
    "Both action channels working as designed. "
    "Two persistent blockers (unchanged from 13:15/13:20/13:25/13:30/13:35/13:40/13:45): "
    "(1) US futures +1.29% > 0.4% threshold - BLOCK state from 13:30:02/56 still in effect. "
    "4h 50m above threshold, no resolution. 09:45 plans contingency FIRM. "
    "(2) STILL BINDING: 13:30 no-new-entries cutoff REACHED 20 min ago. "
    "Conservative override (VIX>13 OR gap>0.5%) still FALSE - market is otherwise eligible "
    "but execution channels + TIME-WINDOW CONSTRAINTS preclude new entry. "
    "14:30 force-square-off is 40 min away. 15:30 monthly NIFTY expiry is 99 min away. "
    "Even if all blockers cleared, no new entry can be placed today. "
    "13:15 FORMAL_SKIP_FOR_DAY_FIRM_AND_BINDING holds at 13:50."
)

ld["rationale"] = (
    "13:50 IST 5-min nochange observation tick per the standard cron schedule. "
    "Last decision 13:45:00 IST (5 min ago) held FORMAL_SKIP_FOR_DAY_FIRM_AND_BINDING. "
    "13:50 is the next scheduled 5-min cron tick to keep brain_actions.json channel fresh. "
    "Key facts (13:45 -> 13:50, 5 min delta): "
    "(a) VIX 10.81 (+0.08 from 13:45s 10.73 - essentially flat, calm 1.0x mult). "
    "(b) candle_regime both still range conf 0.7 (NIFTY 5d range_pct 0.46%, BNF 0.58% per yfinance - "
    "both TIGHT range regime). "
    "(c) 0 open positions unchanged. "
    "(d) No macro blackout. "
    "(e) Bot tick_count advancing on both scanner processes (cycle 9538 process A, cycle 535 process B "
    "per 13:50:25/29 log tail), both alive, both blocking on 13:30 cutoff. "
    "(f) Path bug NOT seen in 13:50 log tail - 30c0fc9 fix confirmed working. "
    "No force-action check failed, no brain-action check failed warnings. "
    "Both action channels working as designed. "
    "Two persistent blockers (unchanged from 13:15/13:20/13:25/13:30/13:35/13:40/13:45): "
    "(1) US futures STILL +1.29% > 0.4% threshold - BLOCK state from 13:30:02/56 still in effect, "
    "4h 50m above threshold, no resolution. "
    "09:45 plans contingency (SKIP entry today entirely if US futures still >0.4%) is FIRM. "
    "(2) STILL BINDING: 13:30 no-new-entries cutoff REACHED 20 min ago per intraday.no_new_trades_after - "
    "operational constraint blocks new entries independently of US futures BLOCK and 0DTE gamma risk. "
    "Conservative override (VIX>13 OR gap>0.5%) still FALSE - market is otherwise eligible. "
    "14:30 force-square-off is 40 min away. 15:30 monthly NIFTY expiry is 99 min away. "
    "Even if all blockers cleared, no new entry can be placed today. "
    "13:15 FORMAL_SKIP_FOR_DAY_FIRM_AND_BINDING holds at 13:50. "
    "No new capital at risk today. No reassessment needed before 14:30 force-square-off."
)

ld["risk_budget_reasoning"] = (
    "Risk budget = 0% new capital for the 13:50 5-min nochange observation tick. "
    "(a) 13:50 is the next scheduled 5-min cron tick - not a planned reassessment point per "
    "13:15/13:20/13:25/13:30/13:35/13:40/13:45 plans. "
    "(b) 13:30 NO-NEW-ENTRIES CUTOFF was REACHED 20 min ago per intraday.no_new_trades_after - "
    "bot log confirms skip firing in SCAN loop on both scanner processes. "
    "This is the BINDING constraint - no new entries can be placed even if US futures BLOCK clears. "
    "(c) US futures STILL +1.29% > 0.4% threshold - BLOCK state from 13:30:02/56 still in effect. "
    "4h 50m above threshold, no resolution. 09:45 plans contingency is FIRM. "
    "(d) Path bug NOT seen in 13:50 log tail - 30c0fc9 fix confirmed working. "
    "(e) Bot Mavis co-pilot independently BLOCKING on US futures gap. "
    "(f) Conservative override (VIX>13 OR gap>0.5%) still FALSE - market is otherwise eligible. "
    "(g) Monthly NIFTY expiry 15:30 (99 min) - 0DTE gamma risk now extreme in final 2h. "
    "(h) 0 open positions, capital 1,09,978 INR, realized +9,978 INR. "
    "(i) Bot alive (tick_count ~111,170 + 22,895 at 13:49:39/41, both blocking). "
    "14:30 force-square-off remains the only working exit (irrelevant with 0 positions, safety net stands). "
    "No new capital at risk today. "
    "13:15 FORMAL_SKIP_FOR_DAY_FIRM_AND_BINDING holds at 13:50."
)

# candle_regime_evidence - update NIFTY and BANKNIFTY reasons
ld["candle_regime_evidence"]["NIFTY"] = {
    "confidence": 0.7,
    "regime": "range",
    "reason": (
        "range=0.46% tight + vix=10.81 low (1.0x mult, +0.08 from 13:45s 10.73 - essentially flat). "
        "5d trend -0.50% (per yfinance, slightly wider than 13:45s -0.44% - still flat). "
        "Live print 24,097.75 yfinance close vs prev close 24,090.85 = +0.03% gap (within 0.5%). "
        "Range regime intact. 5d range_pct 0.46% (same as 13:45). "
        "Still textbook 0DTE iron condor setup per regime, but (a) US futures BLOCK active, "
        "(b) 13:30 no-new-entries cutoff REACHED 20 min ago - BINDING, "
        "(c) 0DTE monthly expiry 99min away - gamma risk extreme. "
        "13:15 FORMAL_SKIP_FIRM_AND_BINDING holds at 13:50 - no new entry today."
    ),
    "range_pct": 0.46,
    "last_close": 24097.75,
    "trend_5d": "down",
    "change_5d_pct": -0.5,
}

ld["candle_regime_evidence"]["BANKNIFTY"] = {
    "confidence": 0.7,
    "regime": "range",
    "reason": (
        "range=0.58% tight + vix=10.81 low (1.0x mult). 5d trend -0.31% (flat, similar to 13:45s -0.23%). "
        "Live print 57,347.20 yfinance close vs prev close 57,509.95 = -0.28% gap (within 0.5%). "
        "BNF slightly weaker from 13:45 (57,391 -> 57,347, -44pt move). "
        "Range regime intact. 5d range_pct 0.58% (same as 13:45). "
        "Still textbook 0DTE iron condor setup per regime, but execution channels closed + "
        "TIME-WINDOW CONSTRAINTS (13:30 cutoff REACHED 20 min ago) now BINDING preclude new entry. "
        "13:15 FORMAL_SKIP_FIRM_AND_BINDING holds at 13:50 - no new entry today."
    ),
    "range_pct": 0.58,
    "last_close": 57347.20,
    "trend_5d": "flat",
    "change_5d_pct": -0.31,
}

# macro_evidence - update minutes_away
ld["macro_evidence"]["upcoming"] = [
    {
        "importance": 2,
        "minutes_away": 99,
        "name": "monthly_expiry_NIFTY",
        "datetime_ist": "2026-08-28 15:30",
    },
    {
        "importance": 2,
        "minutes_away": 1659,
        "name": "india_gdp",
        "datetime_ist": "2026-08-29 17:30",
    },
]
ld["macro_evidence"]["interpretation"] = (
    "No near-term event risk in the 60-min blackout window. "
    "Monthly NIFTY expiry 99 min away at 15:30 (0DTE) - elevated gamma/vol risk in the last 2h, "
    "but not in macro blackout (60-min before window not yet reached - that triggers at 14:30 which is "
    "also force-square-off time). India GDP tomorrow 17:30, well outside window. Macro is QUIET. "
    "The 13:30 no-new-entries cutoff is a separate operational constraint (not a macro event) - "
    "was REACHED 20 min ago, still BINDING. The 14:30 force-square-off is another operational constraint - "
    "40 min away. US futures +1.29% > 0.4% threshold is a separate cautious overlay from the bot "
    "Mavis co-pilot (not macro calendar) - this is the condition that has driven the SKIP-for-day decision. "
    "No material change in macro from 13:45 except clock advancing 5 min. "
    "13:15 FORMAL_SKIP_FIRM_AND_BINDING holds at 13:50 - no new event, no new blackout, "
    "no reassessment warranted before 14:30 force-square-off."
)

ld["research_evidence"]["fallback"] = (
    "Research PDF download still failing (kotak_research.download_latest_research_pdf:52 WARNING at 13:50 - "
    "could not find derivatives PDF URL). Candle+macro+VIX-only mode. "
    "VIX 10.81 (calm, 1.0x multiplier, +0.08 from 13:45s 10.73 - essentially flat). "
    "Bot Mavis co-pilot is blocking on US futures +1.29% > 0.4% threshold - BLOCK state from 13:30:02/56 "
    "still in effect. 13:30 no-new-entries cutoff was REACHED 20 min ago - this is the BINDING constraint "
    "that prevents new entry even if US futures clears. "
    "13:15 FORMAL_SKIP_FIRM_AND_BINDING holds at 13:50. "
    "Even if US futures reversed now, the 13:30 cutoff is REACHED and 0DTE monthly expiry 99min away - "
    "poor risk/reward for fresh entry. SKIP for today, FIRM AND BINDING at 13:50."
)

ld["open_positions_summary"]["note"] = (
    "0 open positions (clean slate, unchanged since 09:46 IST 2026-08-27 EOD square-off). "
    "Capital 1,09,978 INR, realized +9,978 INR for the run-to-date. "
    "Today: monthly NIFTY expiry at 15:30 (99 min) - 0DTE structures with extreme gamma risk in last 2h. "
    "Regular session 4h 50m in. US futures STILL +1.29% > 0.4% threshold - bot Mavis co-pilot STILL BLOCKING "
    "entries (BLOCK state from 13:30:02/56 still in effect). "
    "Path bug NOT seen in 13:50 log tail - 30c0fc9 fix confirmed working. "
    "13:15/13:20/13:25/13:30/13:35/13:40/13:45 FORMAL_SKIP_FIRM_FOR_DAY is FIRM AND BINDING at 13:50 - "
    "13:30 no-new-entries cutoff REACHED 20 min ago per intraday config. "
    "Even if both blockers cleared, no new entry can be placed after 13:30. 0DTE gamma risk extreme. "
    "No fresh entry today. Next meaningful action: 14:30 force-square-off (irrelevant with 0 positions), "
    "then tomorrow 08:25 daily-maintenance + 08:30 daily-start. "
    "Bot alive (tick_count ~111,170 + 22,895 at 13:49:39/41, both blocking)."
)

# tick_context
ld["tick_context"]["previous_decision_ist"] = "2026-08-28 13:45:00"
ld["tick_context"]["decision_change_reason"] = (
    "13:50 IST 5-min nochange observation tick - same call as 13:15/13:20/13:25/13:30/13:35/13:40/13:45 "
    "(HOLD, bias=neutral, 0% new risk, 0 actions). The 13:15/13:30 plan said no more reassessments scheduled; "
    "13:50 is the next scheduled 5-min cron tick to keep brain_actions.json channel fresh. "
    "All blockers unchanged: US futures STILL +1.29% > 0.4% threshold (BLOCK state from 13:30:02/56 still "
    "in effect, 4h 50m above threshold), 13:30 no-new-entries cutoff REACHED 20 min ago (still BINDING), "
    "Path bug still not seen in live bot (30c0fc9 fix confirmed working). "
    "Conservative override (VIX>13 OR gap>0.5%) still FALSE. "
    "13:15 FORMAL_SKIP_FIRM_AND_BINDING holds at 13:50 - same call, fresh tick, no new info, "
    "no new actions, no new risk."
)
ld["tick_context"]["key_change_since_previous"] = (
    "5 min later (13:45 -> 13:50). VIX 10.81 (+0.08 from 13:45s 10.73, essentially flat - 1.0x mult unchanged). "
    "candle_regime both still range conf 0.7 (textbook condor day per regime). "
    "0 open positions unchanged. No macro change. market_session still regular. "
    "Bot tick_count advancing on both processes: "
    "process A scanned cycles 9514/9520/9526/9532/9538 (13:48:25 to 13:50:25), "
    "process B scanned cycles 511/517/523/529/535 (13:48:29 to 13:50:29). "
    "LiveKotak heartbeats: process A 13:48:39 tick_count=110210, 13:49:39 tick_count=111170 (+960 in 60s = 16 ticks/sec). "
    "Process B 13:48:41 tick_count=22280, 13:49:41 tick_count=22895 (+615 in 60s = 10.25 ticks/sec). "
    "13:30 NO-NEW-ENTRIES CUTOFF REACHED 20 min ago - bot SCAN log still shows "
    "'skip: intraday mode - no_new_trades_after (13:30) hit' on both processes. "
    "09:45 plans contingency FIRM since 10:00, reconfirmed at 10:15, observation-only at 10:20/10:25, "
    "recovery at 13:15, nochange at 13:20/13:25, FIRM AND BINDING at 13:30, holds at 13:35/13:40/13:45, "
    "holds at 13:50. 11:30 US cash open did NOT resolve. "
    "Bot Mavis co-pilot independently BLOCKING on US futures. "
    "14:30 force-square-off in 40 min, 15:30 monthly expiry in 99 min. "
    "Even if all blockers cleared, no new entry today. "
    "13:15 FORMAL_SKIP_FIRM_AND_BINDING holds at 13:50."
)
ld["tick_context"]["log_tail_evidence_intraday_cutoff_active"] = (
    "2026-08-28 13:47:58.982 | INFO | __main__:run_paper:1238 | [SCAN] cycle=505 | "
    "skip: intraday mode - no_new_trades_after (13:30) hit | "
    "2026-08-28 13:48:25.061 | INFO | __main__:run_paper:1231 | [SCAN] cycle=9514 | "
    "skip: intraday mode - no_new_trades_after (13:30) hit | "
    "2026-08-28 13:48:29.020 | INFO | __main__:run_paper:1238 | [SCAN] cycle=511 | "
    "skip: intraday mode - no_new_trades_after (13:30) hit | "
    "2026-08-28 13:48:39.324 | INFO | kotak_bot.data.live_feed:_live_kotak_loop:437 | "
    "LiveKotak heartbeat: authed=True subscribed=48 latest=48 tick_count=110210 | "
    "2026-08-28 13:48:41.287 | INFO | kotak_bot.data.live_feed:_live_kotak_loop:437 | "
    "LiveKotak heartbeat: authed=True subscribed=40 latest=40 tick_count=22280 | "
    "2026-08-28 13:48:55.079 | INFO | __main__:run_paper:1231 | [SCAN] cycle=9520 | "
    "skip: intraday mode - no_new_trades_after (13:30) hit | "
    "2026-08-28 13:48:59.041 | INFO | __main__:run_paper:1238 | [SCAN] cycle=517 | "
    "skip: intraday mode - no_new_trades_after (13:30) hit | "
    "2026-08-28 13:49:25.088 | INFO | __main__:run_paper:1231 | [SCAN] cycle=9526 | "
    "skip: intraday mode - no_new_trades_after (13:30) hit | "
    "2026-08-28 13:49:29.081 | INFO | __main__:run_paper:1238 | [SCAN] cycle=523 | "
    "skip: intraday mode - no_new_trades_after (13:30) hit | "
    "2026-08-28 13:49:39.340 | INFO | kotak_bot.data.live_feed:_live_kotak_loop:437 | "
    "LiveKotak heartbeat: authed=True subscribed=48 latest=48 tick_count=111170 | "
    "2026-08-28 13:49:41.311 | INFO | kotak_bot.data.live_feed:_live_kotak_loop:437 | "
    "LiveKotak heartbeat: authed=True subscribed=40 latest=40 tick_count=22895 | "
    "2026-08-28 13:49:55.099 | INFO | __main__:run_paper:1231 | [SCAN] cycle=9532 | "
    "skip: intraday mode - no_new_trades_after (13:30) hit | "
    "2026-08-28 13:49:59.095 | INFO | __main__:run_paper:1238 | [SCAN] cycle=529 | "
    "skip: intraday mode - no_new_trades_after (13:30) hit | "
    "2026-08-28 13:50:25.298 | INFO | __main__:run_paper:1231 | [SCAN] cycle=9538 | "
    "skip: intraday mode - no_new_trades_after (13:30) hit | "
    "2026-08-28 13:50:29.313 | INFO | __main__:run_paper:1238 | [SCAN] cycle=535 | "
    "skip: intraday mode - no_new_trades_after (13:30) hit. "
    "Bot log tail at 13:50 is CLEAN: all entries are 'skip: intraday mode - no_new_trades_after (13:30) hit' "
    "for both scanner processes (cycles 9514/9520/9526/9532/9538 on process A, "
    "cycles 511/517/523/529/535 on process B). LiveKotak heartbeat firing every ~30s on both processes. "
    "No force-action check failed, no brain-action check failed warnings. "
    "Both action channels working as designed."
)

# Header timestamp update
d["timestamp"] = "2026-08-28T08:20:45Z"

# Write back, preserving key order
new_raw = json.dumps(d, indent=2, ensure_ascii=False)
# json.dumps strips trailing whitespace - brain_state.json has the `"history": [` array structure preserved
# because d["history"] is still there as a list.
P.write_text(new_raw, encoding="utf-8")

# Verify
with P.open("r", encoding="utf-8") as f:
    d2 = json.load(f)
print("OK: json valid, last_decision.ist_time =", d2["last_decision"]["ist_time"])
print("VIX:", d2["last_decision"]["vix"])
print("bias:", d2["last_decision"]["bias"])
print("actions_count:", d2["last_decision"]["actions_count"])
print("history_count:", len(d2.get("history", [])))
print("max_positions:", d2["last_decision"]["max_positions"])
print("macro_in_blackout:", d2["last_decision"]["macro_in_blackout"])
print("NIFTY last_close:", d2["last_decision"]["candle_regime_evidence"]["NIFTY"]["last_close"])
print("BNF last_close:", d2["last_decision"]["candle_regime_evidence"]["BANKNIFTY"]["last_close"])
print("monthly expiry minutes_away:", d2["last_decision"]["macro_evidence"]["upcoming"][0]["minutes_away"])
print("gdp minutes_away:", d2["last_decision"]["macro_evidence"]["upcoming"][1]["minutes_away"])
print("previous_decision_ist:", d2["last_decision"]["tick_context"]["previous_decision_ist"])
