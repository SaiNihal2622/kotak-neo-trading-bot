"""
Update brain_state.json's last_decision for the 12:05 IST tick.
HOLD with investigation flag - 12:00 action consumed but no fill,
bot internal Mavis also not placing orders. Order path broken.
"""
import json
import io
import sys
from pathlib import Path

STATE_PATH = Path(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json")

with io.open(STATE_PATH, "r", encoding="utf-8") as f:
    state = json.load(f)

new_decision = {
    "ts": "2026-08-31T06:35:00Z",
    "ist_time": "2026-08-31 12:05:00",
    "bias": "neutral",
    "source": "mavis",
    "max_positions": 0,
    "risk_budget_pct": 0.0,
    "actions": [],
    "decision_summary": "12:05 IST cron tick (5 min after 12:00, 155 min into regular session, market_session=regular). HOLD with INVESTIGATION ESCALATION. (a) The 12:00 re-issuance (act-1200NIFTYIC) was CONSUMED at 12:02:57 (cycle 37277) by the bot's brain_actions reader - confirming the brain_actions.json channel works. BUT ZERO orders landed in paper_state.json (most recent 5 orders from 2026-08-27 14:59:28, ZERO new orders today). (b) Bot's internal Mavis is ALSO firing EXECUTE_PLAN at cycle 2547 (12:05:10) confidence 0.85 with thesis expected_move 168pt and NIFTY spot 24066.85 inside expected range [23922.84, 24258.86] - but the order placement is NOT happening for that path either. (c) This is the 2nd consecutive cron action (after 11:50) that has been consumed without fill. Action channel works (consumed=true). Order placement path appears broken. (d) THESIS UNCHANGED: range regime both conf 0.7, VIX 11.20 calm 1.0x mult (down slightly from 11.25), no IV expansion, macro quiet in_blackout=false no events next 7d, monday brief risk_on posture normal max 2.0% risk preferred_strategies=[bull_call_vertical, iron_condor]. (e) Spot 12:00 -> 12:05: NIFTY 24060.30 -> 24066.85 +6.55pt (slight improvement), BNF 57397.00 -> 57393.30 -3.70pt (slight deterioration but inside Plan A trigger 57300 by +93.30pt). Tape remains in Plan A 2/2 TRIGGERED state. (f) NOT re-issuing action because the bot's internal Mavis is firing EXECUTE_PLAN directly and ALSO not placing orders - the order placement is broken at the bot level, not the action channel. (g) Bias UNCHANGED neutral. Actions CHANGED 1 -> 0 (HOLD). Recommendations for next cron (12:10): check Logs\\bot_stderr.log for new ERRORs related to order_mgr/paper client, check for stuck Lock/mutex, check broker rejection reasons, consider asking user to manually restart the bot. (h) LiveKotak heartbeat 12:05:18 authed=True subscribed=48 latest=48 tick_count=109226 - websocket healthy. Note: tick_count=109226 is a DIFFERENT counter from the 2M+ at 12:00 (was 2,033,840), suggesting a fresh bot process or counter reset. (i) No new entries after 13:30 IST (1h25m away). Force square-off 14:30 IST (2h25m away). 0 open positions, capital 1,09,978 INR, realized +9,978 INR.",
    "rationale": "12:05 IST cron tick (5 min after 12:00, market_session=regular, 155 min into regular session). HOLD with investigation flag. (a) INVESTIGATION ESCALATION: 12:00 re-issuance (act-1200NIFTYIC) was CONSUMED at 12:02:57 (cycle 37277) - brain_actions.json channel works (consumed=true). But ZERO orders in paper_state.json. (b) Bot internal Mavis is ALSO firing EXECUTE_PLAN (cycle 2547 at 12:05:10 NIFTY conf 0.85, cycle 2547 BANKNIFTY BLOCK) - but NOT placing orders. (c) This is the 2nd consecutive cron action (after 11:50) that has been consumed without fill. (d) THESIS UNCHANGED: range regime both conf 0.7, VIX 11.20 calm 1.0x mult, no IV expansion, macro quiet, monday brief risk_on preferred iron_condor, Mavis expected range [23922.84, 24258.86] still contains NIFTY 24066.85. (e) Spot evolution 12:00 -> 12:05: NIFTY 24060.30 -> 24066.85 +6.55pt (slight improvement), BNF 57397.00 -> 57393.30 -3.70pt (slight deterioration). Tape remains in Plan A 2/2 TRIGGERED state. (f) NOT re-issuing the same action because the bot's internal Mavis is firing EXECUTE_PLAN directly and ALSO not placing orders - this strongly suggests the order placement is broken at the bot level, not the action channel. (g) Bias UNCHANGED neutral (thesis intact). Actions CHANGED 1 -> 0 (HOLD). (h) Recommendations for next cron (12:10): check Logs\\bot_stderr.log for new ERRORs related to order_mgr or paper client, check for stuck Lock/mutex, check broker rejection reasons (e.g., session expired, MPIN needed, daily order limit), consider asking user to manually restart the bot, if order path resolves, cron can re-issue at 12:10.",
    "risk_budget_reasoning": "Risk budget = 0pct new capital at 12:05 IST for the Monday regular-session 155-min tick. (a) No new actions issued this tick. (b) Order placement path appears broken - cannot deploy capital even if thesis is valid. (c) Thesis remains valid: range regime both conf 0.7, VIX 11.20 calm, macro quiet, monday brief risk_on preferred iron_condor. (d) Plan A iron_condor remains 2/2 underlying TRIGGERED (NIFTY 24066.85 GT 24020 +46.85pt IMPROVING from +40.30pt at 12:00 by +6.55pt, BNF 57393.30 GT 57300 +93.30pt above TRIGGERED, DETERIORATING from +97.00pt at 12:00 by -3.70pt). (e) Plan B bear_put_vertical: NIFTY 24066.85 NOT < 24000 +66.85pt above REJECTED, BNF 57393.30 NOT < 57250 +143.30pt above REJECTED. 0/3 underlying levels. Plan B NOT triggered. (f) Plan C short_strangle: VIX 11.20 not > 12. Plan C NOT triggered. (g) NOT re-issuing action because the bot's internal Mavis is also firing EXECUTE_PLAN and not placing orders - the order placement is broken, not the action channel. Re-issuing would create a 3rd consumed action with no fill. (h) INVESTIGATION PRIORITY for next cron (12:10): Check Logs\\bot_stderr.log for new ERRORs related to order_mgr, paper client, broker rejection. Check for stuck Lock/mutex. Check if MPIN re-auth needed. If order path resolves, the cron can re-issue.",
    "candle_regime_evidence": {
        "NIFTY": {
            "confidence": 0.7,
            "regime": "range",
            "reason": "range=0.56pct tight (5d) + vix=11.20 calm band 1.0x mult. Live intraday adx 1.4 -> 1.8 UP momentum strengthened. 5d trend -0.63pct DOWN (IMPROVED from -0.65pct at 12:00 by +0.02pct). 5d candles (2026-08-24 to 2026-08-31): 24219.05, 24334.55, 24207.75, 24090.85, 24067.05. Today intraday bar 2026-08-31: open 24117.55 high 24128.70 low 23993.60 close ~24067.05. Live NIFTY at 12:05:10 SCAN = 24066.85 (vs brief close 24090.85 = -24.00pt gap down, IMPROVED from -30.55pt at 12:00 by +6.55pt; vs 09:30 24040 = +26.85pt; vs 24000 round support = +66.85pt ABOVE; vs 24020 Plan A trigger = +46.85pt ABOVE TRIGGERED IMPROVING BUFFER from +40.30pt at 12:00 by +6.55pt; vs 24100 override threshold = -33.15pt BELOW NOT MET; vs 24050 ATM = +16.85pt slightly ITM). adx=1.8 mom=+0.00 momentum recovering in range direction. Range-bound, low-vol, supportive of iron condor. Thesis intact but order path broken.",
            "range_pct": 0.56,
            "last_close": 24066.85,
            "trend_5d": "down",
            "change_5d_pct": -0.63,
        },
        "BANKNIFTY": {
            "confidence": 0.7,
            "regime": "range",
            "reason": "range=0.68pct tight (5d) + vix=11.20 calm band 1.0x mult. Live intraday adx 1.7 -> 1.8 UP momentum maintained. 5d trend -0.23pct FLAT (IMPROVED from -0.24pct at 12:00 by +0.01pct). 5d candles (2026-08-24 to 2026-08-31): 57525.95, 57514.20, 57783.75, 57509.95, 57392.80. Today intraday bar 2026-08-31: open 57353.75 high 57576.25 low 57187.35 close ~57392.80. Live BNF at 12:05:10 SCAN = 57393.30 (vs brief close 57509.95 = -116.65pt gap down, DETERIORATING from -112.95pt at 12:00 by -3.70pt; vs 09:30 57438 = -44.70pt; vs 57300 = +93.30pt ABOVE; vs 57300 Plan A trigger = +93.30pt ABOVE TRIGGERED, DETERIORATING BUFFER from +97.00pt at 12:00 by -3.70pt; vs 57400 override threshold = -6.70pt BELOW NOT MET). adx=1.8 momentum maintained. Range-bound but Mavis plan for NIFTY only. Defer.",
            "range_pct": 0.68,
            "last_close": 57393.3,
            "trend_5d": "flat",
            "change_5d_pct": -0.23,
        },
    },
    "macro_evidence": {
        "upcoming": [],
        "in_blackout": False,
        "interpretation": "macro.upcoming is empty list, in_blackout=false, next_event_min=null. QUIET macro calendar. Monday brief macro_blackout_soon=false, macro_events_next_7d=[]. No RBI policy, Fed, or US CPI in immediate window. Macro layer is QUIET - no event-driven constraint on new entries today. Combined with range regime both conf 0.7 + calm VIX 11.20 + monday brief risk_on + posture normal, the macro layer remains SUPPORTIVE of iron condor. Thesis UNCHANGED. The decision to HOLD is based on the order placement path being broken, not on macro concerns.",
    },
    "research_evidence": {
        "available": False,
        "fallback": "Research PDF download still failing (kotak_research.download_latest_research_pdf:52 WARNING - could not find derivatives PDF URL). Candle+macro+VIX-only mode. No max_pain, PCR, or FII flows available. Defer to: (a) candle_regime both range conf 0.7 (range with mild bullish session-level bias, recovery CONFIRMED at 12:05 with NIFTY +6.55pt, BNF -3.70pt), (b) VIX 11.20 slightly down from 11.25 (calm band, no IV expansion), (c) US S&P +0.74pct / Nasdaq +1.57pct Fri - monday_brief catalyst (5d), (d) US futures recovered from -0.49pct (Mavis EXECUTE_PLAN fired), (e) 0 open positions clean slate, (f) preferred_strategies from brief = [bull_call_vertical, iron_condor] - iron condor is the preferred structure for range regime with brief close recovery, (g) Mavis thesis engine INDEPENDENTLY fired EXECUTE_PLAN for NIFTY iron_condor at confidence 0.85 with thesis expected_move 168pt, range [23922.84, 24258.86], NIFTY spot 24066.85 inside range. No research-driven bias override needed. The decision to HOLD is based on the order placement path being broken, not on research-driven bias.",
    },
    "open_positions_summary": {
        "note": "0 -> 0 open positions this tick (HOLD, no actions). Capital 1,09,978 INR, realized +9,978 INR for the run-to-date. New weekly series started today (2026-08-31 Mon). Bot alive cycle=2547 (12:05:10) tick_count=109,226 (LiveKotak heartbeat 12:05:18 - note this is a DIFFERENT counter from the 2M+ one at 12:00, was 2,033,840 then 2,033,840+). LiveKotak 12:05:18 heartbeat authed=True subscribed=48 latest=48 tick_count=109226 - websocket feed healthy. Bot Mavis EXECUTE_PLAN fired at 12:05:10 cycle 2547 (NIFTY iron_condor conf 0.85) and 12:05:10 cycle 2547 (BANKNIFTY BLOCK). NIFTY 24066.85 +46.85pt above 24020 Plan A trigger TRIGGERED IMPROVING buffer from +40.30pt at 12:00 by +6.55pt. BNF 57393.30 +93.30pt above 57300 Plan A trigger TRIGGERED, DETERIORATING buffer from +97.00pt at 12:00 by -3.70pt. Brief close gap IMPROVED for NIFTY (-24.00pt from -30.55pt at 12:00 by +6.55pt) but DETERIORATED for BNF (-116.65pt from -112.95pt at 12:00 by -3.70pt). INVESTIGATION ESCALATION: 11:50 action (act-1150NIFTYIC) consumed at 11:54:15 (cycle 37174) with no fill. 12:00 action (act-1200NIFTYIC) consumed at 12:02:57 (cycle 37277) with no fill. 2 consecutive cron actions consumed without fill. Bot internal Mavis firing EXECUTE_PLAN also not placing orders. Order placement path is broken, not the action channel. 0 -> 0 positions. Decision: HOLD with investigation flag. Bias neutral UNCHANGED. Next cron (12:10) should investigate order placement path or escalate to user.",
        "details": [],
        "max_reached": False,
        "count": 0,
        "max_positions_limit": 2,
        "post_trade_count": 0,
    },
    "tick_context": {
        "previous_decision_ist": "2026-08-31 12:00:00",
        "previous_decision_bias": "neutral",
        "previous_decision_actions_count": 1,
        "decision_changed": True,
        "decision_change_reason": "12:05 IST cron tick (5 min after 12:00, 155 min into regular session, market_session=regular). Bias UNCHANGED neutral (same as 12:00). Actions CHANGED 1 -> 0 (HOLD instead of re-OPEN). The 12:00 action (act-1200NIFTYIC) was consumed at 12:02:57 (cycle 37277) but ZERO orders landed in paper_state.json (most recent 5 orders from 2026-08-27 14:59:28). The bot's internal Mavis is ALSO firing EXECUTE_PLAN (cycle 2547 at 12:05:10) but ALSO not placing orders. This is the 2nd consecutive cron action (after 11:50) that has been consumed without fill. The action channel works (consumed=true confirms the bot is reading). The order placement path appears broken at the bot level. NOT re-issuing because the bot's internal Mavis is firing EXECUTE_PLAN directly and also not placing orders - this strongly suggests the order placement is broken, not the action channel. The structural decision did NOT change because the underlying thesis remains valid: range regime both conf 0.7, VIX 11.20 calm, macro quiet, monday brief risk_on preferred iron_condor, Mavis expected range [23922.84, 24258.86] still contains NIFTY 24066.85. Tape has IMPROVED (NIFTY +6.55pt) for Plan A. HOLD with investigation flag for next cron (12:10) to check Logs\\bot_stderr.log and order placement path.",
        "monday_brief_summary": {
            "regime_hint": "risk_on",
            "india_open_gap_signal": "gap_up",
            "recommended_posture": "normal",
            "max_risk_per_trade_pct": 2.0,
            "skip_first_30min_per_brief": False,
            "skip_first_30min_per_brief_rationale": "gap_up -> skip 30min (brief internal contradiction: explicit flag=false but rationale recommends skip)",
            "preferred_strategies": ["bull_call_vertical", "iron_condor"],
            "key_catalysts": [
                "S&P +0.74pct Friday - US tailwind for Monday Asia open",
                "Nasdaq +1.57pct Friday - tech rally spillover",
                "India VIX 11.1 - calm, premium-selling favorable",
            ],
            "key_risks": [
                "Bullion/geopolitics (US jobs data, Iran tensions)",
                "Mcap drop of 7 top firms (Bharti Airtel, RIL)",
            ],
            "next_session_open_ist": "2026-08-31T09:15:00",
            "brief_as_of": "2026-08-30T21:01:10+05:30",
        },
        "log_tail_evidence_bot_alive_and_path_broken": "2026-08-31 12:05:07.991 | WARNING | kotak_bot.data.kotak_prod_feed:_fetch_option_quotes:560 | KotakProdFeed: quotes HTTP 400 body={\"fault\":{\"code\":\"400\",\"description\":\"Please set the Neo symbol max value to 50.\",\"message\":\"Please set the Neo symbol max value to 50.\"}} | 2026-08-31 12:05:10.124 | INFO    | __main__:run_paper:1354 | [SCAN] cycle=2547 NIFTY spot=24066.85 atm=24050 opts=18 regime=range conf=0.40 adx=1.8 mom=-0.00 | 2026-08-31 12:05:10.125 | INFO    | __main__:run_paper:1432 | [MAVIS] cycle=2547 NIFTY | EXECUTE_PLAN: iron_condor confidence=0.85 reason=mavis_override: NIFTY spot 24090.85 inside expected range [23922.84, 24258.86] (thesis expected_move 168pt). Sell wings | 2026-08-31 12:05:10.208 | INFO    | __main__:run_paper:1354 | [SCAN] cycle=2547 BANKNIFTY spot=57393.30 atm=57400 opts=18 regime=range conf=0.40 adx=1.8 mom=-0.00 | 2026-08-31 12:05:10.211 | INFO    | __main__:run_paper:1424 | [MAVIS] cycle=2547 BANKNIFTY | BLOCK: Mavis plan is for NIFTY, not BANKNIFTY | 2026-08-31 12:05:18.332 | INFO    | kotak_bot.data.live_feed:_live_kotak_loop:437 | LiveKotak heartbeat: authed=True subscribed=48 latest=48 tick_count=109226",
    },
    "actions_count": 0,
    "timestamp": "2026-08-31T06:35:00Z",
    "note": "investigate_no_orders_landing_v2",
}

state["last_decision"] = new_decision
state["timestamp"] = "2026-08-31T06:35:00Z"
state["call_count_today"] = state.get("call_count_today", 0) + 1

with io.open(STATE_PATH, "w", encoding="utf-8") as f:
    json.dump(state, f, indent=2, ensure_ascii=False)
    f.write("\n")

print("OK - last_decision updated for 12:05 IST HOLD/investigate")
print(f"  ts: {new_decision['ts']}")
print(f"  ist_time: {new_decision['ist_time']}")
print(f"  bias: {new_decision['bias']}")
print(f"  actions: {len(new_decision['actions'])}")
print(f"  note: {new_decision['note']}")
print(f"  call_count_today: {state['call_count_today']}")
