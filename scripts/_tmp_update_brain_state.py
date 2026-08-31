#!/usr/bin/env python3
"""One-shot update of brain_state.json: replace only last_decision, preserve history."""
import json
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))
now_ist = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

path = r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json"
with open(path, "r", encoding="utf-8") as f:
    state = json.load(f)

new_decision = {
    "ts": now_utc,
    "timestamp": now_utc,
    "ist_time": now_ist,
    "bias": "cautious",
    "source": "mavis",
    "max_positions": 2,
    "actions": [],
    "note": (
        f"{now_ist[11:].replace(':', '')[:4]}_regular_mon_5min_tick_tape_extends_gap_down_further_after_09_50_midway_bounce_failed_"
        "NIFTY_now_24016_minus_13pt_from_09_50_BNF_57314_minus_36pt_from_09_50_"
        "VIX_11.20_plus_0.04_from_09_50_still_calm_1.0x_mult_"
        "candle_regime_5d_both_range_conf_0.7_bot_live_intraday_range_conf_0.40_"
        "5d_trend_NIFTY_minus_0.66pct_BNF_minus_0.44pct_unchanged_"
        "0_open_positions_clean_slate_capital_109978_realized_9978_"
        "bot_alive_tick_2027448_at_09_55_30_LiveKotak_heartbeat_firing_"
        "DECISION_HOLD_cautious_0_actions_0pct_risk_budget_"
        "09_35_iron_condor_plan_DEFINITIVELY_INVALIDATED_NIFTY_now_24016_74pt_below_24030_floor_"
        "BNF_57314_36pt_below_57350_floor_"
        "09_50_midway_bounce_also_failed_tape_rolled_over_again_"
        "bot_Mavis_pre_market_filter_STILL_BLOCKING_with_US_futures_minus_0.49pct_greater_than_0.4pct_threshold_"
        "log_09_55_36_37_cycle_999_both_NIFTY_BANKNIFTY_BLOCK_"
        "Bot_will_reject_any_OPEN_regardless_of_LLM_bias_so_writing_HOLD_keeps_with_09_50_decision_consistency_"
        "Telegram_will_dedup_bias_cautious_actions_0_risk_0_"
        "at_10_00_reassess_full_15min_candle_9_45_10_00_settled_AND_check_US_futures_gap_closure_for_bot_gate_clear_"
        "secondary_contingency_bear_put_vertical_getting_closer_but_NOT_triggered_"
        "NIFTY_24016_still_16pt_above_24000_BNF_57313_still_63pt_above_57250"
    ),
    "market_session": "regular",
    "vix": 11.20,
    "risk_budget_pct": 0,
    "bias_decision": "cautious",
    "macro_in_blackout": False,
    "decision_summary": (
        "09:55 IST cron tick (5 min after 09:50 midway check, 25 min into regular session). "
        "Tape CONTINUES the gap-down extension: NIFTY 24032.75 -> 24016.10 = -16.65pt in 5 min (vs -62pt from brief close 24091). "
        "BNF 57363.15 -> 57313.55 = -49.60pt in 5 min (vs -196pt from brief close 57510). "
        "The 09:50 mid-tick bounce that briefly brought NIFTY back above 24030 and BNF back above 57350 has FAILED. "
        "09:35 iron_condor plan DEFINITIVELY INVALIDATED: NIFTY 24016.10 is now 13.90pt below the 24030 floor (and 74pt below at 09:35 measurement), "
        "BNF 57313.55 is 36.45pt below 57350 floor. Bot Mavis pre-market filter STILL BLOCKING with US futures -0.49% > 0.4% threshold "
        "(visible in log 09:55:36-37 cycle=999 for both NIFTY and BANKNIFTY). "
        "VIX 11.20 calm band, 1.0x mult, +0.04 from 09:50 - no IV expansion, but tape is steadily bleeding lower. "
        "candle_regime 5d both range conf 0.7 (consistent with brief). 5d trend NIFTY -0.66%, BNF -0.44% (both slight down). "
        "Macro quiet, no events, no blackout. Research unavailable (PDF download still failing). "
        "0 open positions, clean slate, capital 1,09,978 INR, realized +9,978 INR. "
        "Bot alive (tick 2,027,448 at 09:55:30 LiveKotak heartbeat). "
        "09:35 secondary contingency (bear_put_vertical if gap extends below 24000/57250) is getting closer but NOT triggered: "
        "NIFTY 24016 still 16pt above 24000, BNF 57313 still 63pt above 57250. "
        "If tape breaks below 24000/57250 in next 5 min AND bot gate clears, then bear_put_vertical becomes valid. "
        "DECISION: HOLD/cautious/0 actions, defer to 10:00 IST. "
        "At 10:00: reassess full 15-min candle 9:45-10:00 settled AND check US futures gap closure for bot gate clear. "
        "If bot gate clears AND NIFTY > 24020 AND BNF > 57300, then iron_condor at 60-odds risk 2.0%. "
        "If bot gate clears AND (NIFTY < 24000 OR BNF < 57250), then bear_put_vertical risk 2.0% max 1 lot NIFTY. "
        "If VIX > 12 AND bot gate clears, then short_strangle. "
        "Risk budget = 0% at 09:55, max 2.0% available at 10:00+ if conditions warrant and bot gate clears."
    ),
    "rationale": (
        "09:55 IST cron tick (5 min after 09:50, market_session=regular, 25 min into regular session). "
        "(a) Live tape evolution 09:50 -> 09:55: NIFTY 24032.75 -> 24016.10 = -16.65pt (5 min - small but continues the drift); "
        "BNF 57363.15 -> 57313.55 = -49.60pt (5 min - real money move, accelerating). "
        "Full session 09:30 -> 09:55: NIFTY 24040 -> 24016.10 = -23.90pt; BNF 57438 -> 57313.55 = -124.45pt. "
        "(b) The 09:50 midway bounce (NIFTY 24032.75 above 24030 floor by 2.75pt) has FAILED - tape rolled back over. "
        "(c) 09:35 iron_condor plan DEFINITIVELY INVALIDATED: NIFTY 24016.10 < 24030 by 13.90pt, BNF 57313.55 < 57350 by 36.45pt. "
        "Both underlyings are now deeply below the iron_condor floors. "
        "(d) Bot Mavis pre-market filter STILL BLOCKING with US futures -0.49% > 0.4% threshold. "
        "Log line 09:55:36 cycle=999 NIFTY: 'BLOCK by Mavis: mavis_decision.action=BLOCK is not EXECUTE_PLAN - bot requires explicit EXECUTE_PLAN to enter. reason=Mavis pre-market BLOCK: US futures m...' "
        "Log line 09:55:37 cycle=999 BANKNIFTY: same BLOCK message. "
        "This is the BINDING CONSTRAINT - any OPEN will be rejected by the bot regardless of LLM bias. "
        "(e) VIX 11.20 calm band, 1.0x mult, +0.04 from 09:50 (11.16), +0.13 from 09:45 (11.07). Slight uptick but well within calm threshold (<12). No IV expansion. "
        "(f) candle_regime 5d both range conf 0.7. candle_regime bot live intraday both range conf 0.40 (unchanged). "
        "(g) 5d trend NIFTY -0.66% (slight down, stable from 09:50), BNF -0.44% (flat, stable from 09:50). "
        "(h) Bot alive: process A tick 2,027,448 (heartbeat at 09:55:30) - up from 2,019,010 at 09:50 = +8,438 ticks in 5 min. "
        "(i) Brief thesis still invalidated: NIFTY 24016 = -75pt from brief close 24091 (extended from -58pt at 09:50, -62pt at 09:45, -40pt at 09:35). "
        "BNF 57314 = -196pt from brief close 57510 (extended from -147pt at 09:50, -161pt at 09:45, -70pt at 09:35). "
        "Both underlyings continue to extend gap-down vs brief expectations. "
        "(j) Macro quiet, no events, no blackout. "
        "(k) Research unavailable (PDF download still failing). "
        "(l) 0 open positions, capital 1,09,978 INR, realized +9,978 INR. "
        "(m) Operational constraint: bot gate blocks OPEN regardless of LLM bias. Plus, the 09:35/09:50 contingent plans are both fully invalidated. "
        "(n) Secondary contingency (bear_put_vertical) is now closer but NOT triggered: NIFTY 24016 still 16pt above 24000 floor, BNF 57313 still 63pt above 57250 floor. "
        "If tape breaks below 24000/57250 in next 5 min AND bot gate clears, then bear_put_vertical becomes valid. "
        "(o) Decision: HOLD/cautious/0 actions. "
        "(p) At 10:00, contingent plan: IF US futures gap closes AND bot gate clears AND (NIFTY > 24020 AND BNF > 57300) THEN iron_condor at 60-odds, risk 2.0%. "
        "IF bot gate clears AND (NIFTY < 24000 OR BNF < 57250) THEN bear_put_vertical risk 2.0% max 1 lot NIFTY. "
        "IF VIX > 12 AND bot gate clears THEN short_strangle. ELSE continue HOLD. "
        "(q) Note: Kotak PROD option quotes are still returning HTTP 400 (Neo symbol max value 50 - upstream API quirk, not a bot bug), so option chain data is patchy. Spot price ticks are healthy."
    ),
    "risk_budget_reasoning": (
        "Risk budget = 0% new capital at 09:55 IST for the Monday regular-session 25-min transition tick. "
        "(a) 09:35 iron_condor contingency plan thresholds FAILED TWICE NOW: at 09:50 (NIFTY 24032.75 above 24030 by 2.75pt, BNF 57363.15 above 57350 by 13.15pt) "
        "and DEFINITIVELY at 09:55 (NIFTY 24016.10 below 24030 by 13.90pt, BNF 57313.55 below 57350 by 36.45pt). "
        "(b) Bot Mavis pre-market filter STILL BLOCKING entries with US futures -0.49% > 0.4% threshold. "
        "Bot will reject any OPEN from brain_actions.json per its gate (log evidence at 09:55:36-37 cycle=999). "
        "(c) VIX 11.20 calm band, 1.0x mult, +0.04 from 09:50 - slight uptick but no volatility expansion. "
        "(d) Conservative override triggered: (i) brief gap_up thesis INVALIDATED by live tape (NIFTY -75pt from brief close, BNF -196pt from brief close), "
        "(ii) bot gate still blocking, (iii) 09:35 plan thresholds failed (twice - at 09:50 and 09:55), "
        "(iv) 09:50 mid-tick bounce failed (tape rolled back over), (v) tape continues to extend gap-down in 5-min candles. "
        "(e) 0 open positions, no existing risk. "
        "(f) Monday brief posture=normal = max 2.0% new risk per trade eligible at 10:00+ if conditions warrant. "
        "(g) Brief-thesis-gone (live tape extends gap-down further) + bot-gate-blocks + 09:35/09:50-plans-failed = cautious, defer until 10:00. "
        "(h) No macro events, no blackout. (i) Research unavailable. "
        "(j) preferred_strategies from brief = [bull_call_vertical, iron_condor] - brief thesis invalidated, plus bot gate blocks. "
        "(k) Bot alive. "
        "(l) 0% new risk at 09:55, max 2.0% available at 10:00+ if conditions warrant and bot gate clears AND tape stabilizes OR secondary contingency triggers."
    ),
    "candle_regime_evidence": {
        "NIFTY": {
            "confidence": 0.4,
            "regime": "range",
            "reason": "range=0.86% tight (5d) + vix=11.20 calm band 1.0x mult. Bot live intraday calc shows conf 0.40 (unchanged from 09:50). 5d trend -0.66% per yfinance (stable from 09:50, slight down). 5d candles (2026-08-21 to 2026-08-27): 24252, 24219, 24335, 24208, 24091 - last 5d close 24091 is the lowest in 5d (Friday's close). Today pre-market bar 2026-08-31: open 24117.55 high 24128.70 low 24019.55 close 24029.20 - 109pt pre-market range (0.45% of open). Opening 15-min candle (9:30-9:45) settled: open 24040 high 24053.90 low 24019.55 close 24029.20 - bearish body -10.80pt, 24pt range. Live NIFTY at 09:55 = 24016.10 (vs brief close 24091 = -75pt gap down, vs Friday close 24090.85 = -75pt gap down, vs 09:30 24040 = -23.90pt, vs 09:35 24050.75 = -34.65pt, vs 09:50 24032.75 = -16.65pt). 5-min candle 9:50-9:55 in progress at 09:55:42 (will settle at 10:00). NIFTY broke through 24030 floor decisively at 09:55, now 16pt above the 24000 bear_put_vertical trigger. Range structure weakening on downside; if 24000 breaks, regime flip to trending_down. Defer to 10:00 with full 15-min candle (9:45-10:00) settled."
        },
        "BANKNIFTY": {
            "confidence": 0.4,
            "regime": "range",
            "reason": "range=0.87% tight (5d) + vix=11.20 calm band 1.0x mult. Bot live intraday calc shows conf 0.40 (unchanged from 09:50). 5d trend -0.44% per yfinance (stable from 09:50, flat). 5d candles (2026-08-21 to 2026-08-27): 57762, 57526, 57514, 57784, 57510 - last 5d close 57510 is mid-range. Today pre-market bar 2026-08-31: open 57353.75 high 57576.25 low 57238.50 close 57349.75 - 338pt pre-market range (0.59% of open). Opening 15-min candle (9:30-9:45) settled: open 57438 high 57439.45 low 57349.75 close 57349.75 - strongly bearish body -88.25pt CLOSING AT THE LOW. Live BNF at 09:55 = 57313.55 (vs brief close 57510 = -196pt gap down, vs Friday close 57509.95 = -196pt gap down, vs 09:30 57438 = -124.45pt, vs 09:35 57439.45 = -125.90pt, vs 09:50 57363.15 = -49.60pt). BNF is now 63pt above the 57250 bear_put_vertical trigger. 5-min candle 9:50-9:55 in progress at 09:55:42 (will settle at 10:00). BNF is the weakest of the two - significant 5-min drift from 09:50 to 09:55 (-49.60pt). Range structure weakening; if 57250 breaks, regime flip to trending_down. Defer to 10:00 with full 15-min candle (9:45-10:00) settled."
        },
        "range_pct": 0.87,
        "last_close": 57313.55,
        "trend_5d": "flat",
        "change_5d_pct": -0.44
    },
    "macro_evidence": {
        "upcoming": [],
        "in_blackout": False,
        "interpretation": "macro.upcoming is empty list, in_blackout=false, next_event_min=null. QUIET macro calendar. Monday brief macro_blackout_soon=false, macro_events_next_7d=[]. No RBI policy, Fed, or US CPI in immediate window. New weekly series starts today (Monday after Friday monthly NIFTY expiry). Macro layer is QUIET - no event-driven constraint on new entries today. The bot Mavis pre-market BLOCK is NOT from macro - its from US futures -0.49% gap signal. Macro does not override the bot gate. Combined with range regime + calm VIX + monday brief risk_on + posture normal, the macro layer would be supportive of iron condor or bull_call_vertical post-09:30 - BUT live tape gap_down extends further, 09:35/09:50 plan thresholds failed, and bot gate still blocks. Defer to 10:00."
    },
    "research_evidence": {
        "available": False,
        "fallback": "Research PDF download still failing (kotak_research.download_latest_research_pdf:52 WARNING at 09:55 - could not find derivatives PDF URL). Candle+macro+VIX-only mode. No max_pain, PCR, or FII flows available. Defer to: (a) candle_regime both range conf 0.4-0.7 (mixed signal, leaning range), (b) VIX 11.20 calm (volatility favorable for premium-selling in principle), (c) US S&P +0.72% / Nasdaq +1.57% Fri - monday_brief catalyst, (d) US futures -0.49% - REAL-TIME gap signal contradicting brief AND still blocking bot gate, (e) 0 open positions clean slate, (f) preferred_strategies from brief = [bull_call_vertical, iron_condor] - but live tape contradicts both and bot gate blocks. No research-driven bias override."
    },
    "open_positions_summary": {
        "note": "0 open positions (clean slate since 2026-08-27 EOD square-off). Capital 1,09,978 INR, realized +9,978 INR for the run-to-date. Friday 2026-08-28 EOD was HOLD (0 positions, monthly NIFTY expiry passed clean). Weekend: no new positions. New weekly series starts today (2026-08-31 Mon). Bot alive (process A tick 2,027,448 at 09:55:30 + process B still firing, LiveKotak heartbeat every ~30s). REGULAR session - 25 min in. Bot main loop scan is in regular mode (log shows [SCAN] cycle=999 at 09:55:36 with regime=range conf=0.40 not skip). HOWEVER bot own Mavis pre-market filter is STILL BLOCKING entries with reason US futures -0.49% (threshold 0.4%) - visible in log line 09:55:36 for NIFTY and 09:55:37 for BANKNIFTY. The 09:35 bear_put_vertical secondary contingency is now closer (NIFTY 24016 still 16pt above 24000, BNF 57313 still 63pt above 57250), but bot gate still blocks. 5-min candle 9:50-9:55 in progress; will settle at 10:00. Next meaningful action: 10:00 with full 15-min candle (9:45-10:00) settled AND check if US futures have closed the gap to clear bot gate. Note: Kotak PROD option quotes are returning HTTP 400 (Neo symbol max value 50 - upstream API quirk, not a bot bug), so option chain data is patchy but spot ticks are healthy.",
        "details": [],
        "max_reached": False,
        "count": 0,
        "max_positions_limit": 2
    },
    "tick_context": {
        "previous_decision_ist": "2026-08-31 09:50:30",
        "previous_decision_bias": "cautious",
        "previous_decision_actions_count": 0,
        "decision_changed": False,
        "decision_change_reason": "09:55 IST cron tick (5 min after 09:50, 25 min into regular session). Bias unchanged cautious (same as 09:50 and 09:45). Actions unchanged (empty). The structural decision is the same: HOLD/cautious/0 actions. However, the TAPE HAS EVOLVED NEGATIVELY: NIFTY 24032.75 -> 24016.10 = -16.65pt in 5 min (and now 13.90pt below the 24030 floor). BNF 57363.15 -> 57313.55 = -49.60pt in 5 min (and now 36.45pt below the 57350 floor). The 09:50 mid-tick bounce that briefly brought both underlyings above their respective floors has FAILED. The 09:35 iron_condor plan is now DEFINITIVELY INVALIDATED. The 09:35 secondary contingency (bear_put_vertical) is now closer (NIFTY 24016 still 16pt above 24000 trigger, BNF 57313 still 63pt above 57250 trigger). Bot Mavis pre-market filter STILL BLOCKING with US futures -0.49% > 0.4% (visible in log 09:55:36-37 cycle=999 for both NIFTY and BANKNIFTY). Bot alive (process A tick 2,027,448 at 09:55:30). VIX 11.20 +0.04 from 09:50 (calm, no IV expansion). candle_regime both range conf 0.40 (unchanged). 5d trend NIFTY -0.66% (stable from 09:50), BNF -0.44% (stable from 09:50). Brief thesis invalidated further: NIFTY 24016 = -75pt from brief close 24091 (extended from -58pt at 09:50, -62pt at 09:45, -40pt at 09:35), BNF 57314 = -196pt from brief close 57510 (extended from -147pt at 09:50, -161pt at 09:45, -70pt at 09:35). Decision: HOLD/cautious/0 actions unchanged. Telegram will dedup since bias+actions+risk all match 09:50.",
        "key_change_since_previous": "Tick_count advanced: process A 2,019,010 -> 2,027,448 (+8,438 ticks in 5 min). VIX +0.04 (11.16 -> 11.20, still calm, slight uptick). market_session: regular (continuous since 09:30). NIFTY live print drift: 24032.75 -> 24016.10 (-16.65pt in 5 min, -23.90pt in 25 min). BNF live print drift: 57363.15 -> 57313.55 (-49.60pt in 5 min, -124.45pt in 25 min). 5d trend NIFTY -0.66% (stable), BNF -0.44% (stable). CRITICAL: 09:35 plan thresholds FAILED DEFINITIVELY at 09:55. NIFTY broke 24030 floor by 13.90pt. BNF broke 57350 floor by 36.45pt. 09:35 iron_condor contingency fully invalidated. 09:35 bear_put_vertical secondary contingency now closer (NIFTY 24016 still 16pt above 24000, BNF 57313 still 63pt above 57250). Bot Mavis pre-market filter STILL BLOCKING with US futures -0.49% > 0.4% (visible in log 09:55:36-37 cycle=999 for both underlyings). No Telegram dedup concern: bias stayed cautious, actions_count stayed 0, send_trader_tg.py will dedup. Note: Kotak PROD option quotes are returning HTTP 400 (Neo symbol max value 50 - upstream API quirk, not a bot bug), so option chain data is patchy but spot ticks are healthy.",
        "monday_brief_summary": {
            "regime_hint": "risk_on",
            "india_open_gap_signal": "gap_up",
            "recommended_posture": "normal",
            "max_risk_per_trade_pct": 2.0,
            "skip_first_30min_per_brief": False,
            "skip_first_30min_per_brief_rationale": "gap_up -> skip 30min (brief internal contradiction: explicit flag=false but rationale recommends skip)",
            "preferred_strategies": ["bull_call_vertical", "iron_condor"],
            "key_catalysts": [
                "S&P +0.72% Friday - US tailwind for Monday Asia open",
                "Nasdaq +1.57% Friday - tech rally spillover",
                "India VIX 11.1 - calm, premium-selling favorable"
            ],
            "key_risks": [
                "Bullion/geopolitics (US jobs data, Iran tensions)",
                "Mcap drop of 7 top firms (Bharti Airtel, RIL)"
            ],
            "next_session_open_ist": "2026-08-31T09:15:00",
            "brief_as_of": "2026-08-30T21:01:10+05:30"
        },
        "log_tail_evidence_bot_alive_and_blocking": "2026-08-31 09:55:30.988 | INFO | kotak_bot.data.live_feed:_live_kotak_loop:437 | LiveKotak heartbeat: authed=True subscribed=52 latest=50 tick_count=2027448 | 2026-08-31 09:55:36.978 | INFO | __main__:run_paper:1354 | [SCAN] cycle=999 NIFTY spot=24016.10 atm=24000 opts=18 regime=range conf=0.40 adx=1.5 mom=-0.00 | 2026-08-31 09:55:36.979 | INFO | __main__:run_paper:1412 | [MAVIS] cycle=999 NIFTY | BLOCK by Mavis: mavis_decision.action='BLOCK' is not EXECUTE_PLAN — bot requires explicit EXECUTE_PLAN to enter. reason=Mavis pre-market BLOCK: US futures m | 2026-08-31 09:55:37.016 | INFO | __main__:run_paper:1354 | [SCAN] cycle=999 BANKNIFTY spot=57313.55 atm=57300 opts=18 regime=range conf=0.40 adx=0.9 mom=-0.00 | 2026-08-31 09:55:37.017 | INFO | __main__:run_paper:1412 | [MAVIS] cycle=999 BANKNIFTY | BLOCK by Mavis: mavis_decision.action='BLOCK' is not EXECUTE_PLAN — bot requires explicit EXECUTE_PLAN to enter. reason=Mavis pre-market BLOCK: US futures m"
    },
    "actions_count": 0
}

state["last_decision"] = new_decision
state["call_count_today"] = state.get("call_count_today", 0) + 1
state["timestamp"] = now_utc

with open(path, "w", encoding="utf-8") as f:
    json.dump(state, f, indent=2, ensure_ascii=False)

print(f"OK: last_decision updated at {now_ist} (UTC {now_utc})")
print(f"bias={new_decision['bias']} actions={new_decision['actions_count']} risk={new_decision['risk_budget_pct']}%")
print(f"history entries preserved: {len(state.get('history', []))}")
