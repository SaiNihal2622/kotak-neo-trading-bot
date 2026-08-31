#!/usr/bin/env python
"""One-shot updater for brain_state.json 13:25 IST tick."""
import json
import sys

FP = r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json"

NEW_DECISION = {
    "ts": "2026-08-31T07:55:00Z",
    "ist_time": "2026-08-31 13:25:00",
    "bias": "cautious",
    "source": "mavis",
    "max_positions": 0,
    "actions": [],
    "note": "p1_blocker_http400_batch_size_18th_consecutive_tick_dual_mavis_3507_plus_38263_5min_to_cutoff_fix_window_now_terminal",
    "decision_summary": (
        "13:25 IST cron tick (5 min after 13:20, 235 min into regular session, market_session=regular). "
        "HOLD, 0 actions, bias UNCHANGED cautious. "
        "(a) ROOT CAUSE UNCHANGED: HTTP 400 'Please set the Neo symbol max value to 50' still firing every 2-3 sec "
        "on kotak_bot/data/kotak_prod_feed.py:_fetch_option_quotes:560 (fresh bot log tail 13:25:02 to 13:25:28 = "
        "10 warnings in 26s window). 18th CONSECUTIVE TICK of structural blocker "
        "(11:50, 12:00, 12:10, 12:15, 12:20, 12:25, 12:30, 12:35, 12:40, 12:45, 12:50, 12:55, 13:00, 13:05, 13:10, "
        "13:15, 13:20, 13:25). 95 min of blocked execution since first identification at 11:50. "
        "(b) Live spot evolution 13:20 -> 13:25: NIFTY 24066.65 -> 24066.85 +0.20pt (essentially FLAT, holding above 24065). "
        "BNF last print 57391.70 at 13:20 - no fresh BNF print in 13:25 log tail. "
        "(c) BUFFERS 13:20->13:25: NIFTY 24066.85 GT 24020 +46.85pt (UNCHANGED from +46.65pt at 13:20, still >40pt healthy), "
        "BNF 57391.70 GT 57300 +91.70pt (UNCHANGED from 13:20, still well above trigger). "
        "Plan A iron_condor still 2/2 underlying TRIGGERED with healthy buffers. "
        "(d) FIX WINDOW NOW TERMINAL: 5 min to 13:30 HARD limit (was 10 min at 13:20). This is the LAST tick where any new "
        "entry is even theoretically possible, but the order path is STILL blocked by HTTP 400. Even with the most aggressive "
        "optimistic path (deploy NOW + 3min restart + first scan = ~13:28-13:30), no realistic filled entry before 13:30. "
        "The current paper session is now effectively closed for new entries. "
        "(e) Plan B bear_put_vertical 0/2 (NIFTY 24066.85 NOT < 24000, BNF 57391.70 NOT < 57250). "
        "Plan C short_strangle NOT triggered (VIX 11.18 not > 12). "
        "(f) Bot-internal Mavis cycle=38263 at 13:25:28 EXECUTE_PLAN NIFTY iron_condor conf=0.85 - blocked by HTTP 400. "
        "DUAL MAVIS ANOMALY PERSISTS: cycle=3507 (current, +60 from 13:20 cycle=3447) AND cycle=38263 (orphan, +60 from 13:20 "
        "cycle=38203) within 1.5s. Both fire EXECUTE_PLAN. Orphan bot process pattern from AGENTS.md. "
        "(g) VIX 11.18 calm 1.0x mult. Macro quiet, in_blackout=false, upcoming=[]. "
        "(h) 5d candle regime UNCHANGED on 13:25: NIFTY range_pct 0.56% (5d), BNF range_pct 0.68% (5d). Range thesis still INTACT. "
        "(i) 0 open positions. Capital Rs.1,09,978, realized +Rs.9,978. "
        "(j) Bias UNCHANGED cautious - 12:15 escalation already surfaced P1 to user. "
        "(k) TIME-BUDGET (TERMINAL): 5 min to 13:30 cutoff (HARD limit, no new entries after), "
        "1h05m to 14:30 force-square-off (N/A - 0 positions), 2h05m to 15:30 close. "
        "The HTTP 400 fix is NO LONGER ACTIONABLE for this session. The fix is still valuable for FUTURE sessions (Sep 1, Tue)."
    ),
    "rationale": (
        "13:25 IST cron tick (5 min after 13:20, market_session=regular, 235 min into regular session). "
        "HOLD, 0 actions, bias UNCHANGED cautious. "
        "(a) Structural blocker UNCHANGED: HTTP 400 'Please set the Neo symbol max value to 50' still firing every 2-3 sec "
        "on kotak_bot/data/kotak_prod_feed.py:_fetch_option_quotes:560. 10 warnings in the 26s window 13:25:02 to 13:25:28. "
        "Execution path for any new options order (iron condor pricing, Mavis EXECUTE_PLAN, post-decision quote fetch) is BLOCKED. "
        "(b) 18th CONSECUTIVE TICK of the same structural blocker. 95 min of blocked execution since 11:50 IST. "
        "(c) Live spot evolution 13:20 -> 13:25: NIFTY +0.20pt essentially FLAT (24066.85 vs 24066.65 at 13:20, holding above 24065), "
        "BNF last print 57391.70 at 13:20 (no fresh print in 13:25 log tail). "
        "Plan A iron_condor still 2/2 underlying TRIGGERED with healthy buffers: "
        "NIFTY 24066.85 GT 24020 +46.85pt (UNCHANGED from +46.65pt, still >40pt), "
        "BNF 57391.70 GT 57300 +91.70pt (UNCHANGED from 13:20). "
        "(d) FIX WINDOW NOW TERMINAL: 5 min to 13:30 HARD limit (was 10 min at 13:20). This is the LAST tick where new entries are "
        "even theoretically possible. Even with the most optimistic path (deploy NOW + 3min restart + first scan = ~13:28-13:30), "
        "no realistic filled entry before 13:30. The current paper session is now effectively closed for new entries. "
        "(e) Plan B bear_put_vertical still 0/2 (NIFTY 24066.85 NOT < 24000, BNF 57391.70 NOT < 57250). "
        "Plan C short_strangle NOT triggered (VIX 11.18 not > 12). "
        "(f) Bot-internal Mavis cycle=38263 EXECUTE_PLAN NIFTY iron_condor conf=0.85 "
        "(NIFTY spot 24066.85 inside expected range [23922.84, 24258.86], thesis expected_move 168pt) - "
        "same as 13:20/13:15/13:10/13:05/13:00 - blocked by HTTP 400. "
        "(g) DUAL MAVIS ANOMALY PERSISTS: cycle=3507 (current) + cycle=38263 (orphan) in bot log tail (13:25:28 within 1.5s) - "
        "orphan bot process pattern from AGENTS.md. Tick count gap: orphan LiveKotak heartbeat at 13:25:19 shows tick_count=168600 (orphan); "
        "current bot heartbeat at 13:20:33 was tick_count=2038028 (no fresh heartbeat in 13:25 tail). "
        "(h) VIX 11.18 calm 1.0x mult, no IV expansion. Macro quiet. "
        "(i) Candle regime 5d (per yfinance refresh at 13:25): NIFTY range_pct 0.56%, BNF range_pct 0.68% (UNCHANGED from 13:20). "
        "5d trend NIFTY -0.63% (UNCHANGED from 13:20), BNF -0.21% (vs -0.23% at 13:20, slightly IMPROVED). "
        "Both still classified range conf 0.7. Thesis INTACT. "
        "(j) Research unavailable. "
        "(k) 0 open positions, capital Rs.1,09,978, realized +Rs.9,978. "
        "(l) NOT re-issuing iron_condor action because: (i) the order path is structurally blocked by HTTP 400, "
        "(ii) the fix window has TERMINALLY CLOSED (5 min to 13:30 HARD limit, no new entries after), "
        "(iii) re-issuing would just create another consumed action with no fill, "
        "(iv) the fix requires a code change + bot restart, NOT a cron decision. "
        "(m) Bias UNCHANGED cautious. "
        "(n) USER-ACTIONABLE PATHS UNCHANGED: (i) HTTP 400 fix = chunk symbols into <=50 batches in "
        "kotak_bot/data/kotak_prod_feed.py:_fetch_option_quotes around line 560, "
        "(ii) nssm restart KotakBotPaper to pick up new code, "
        "(iii) orphan bot process needs admin UAC for taskkill /F /T /PID, "
        "(iv) investigate the dual Mavis cycle anomaly (cycles 3507 + 38263). "
        "(o) Time-budget (TERMINAL): 5 min to 13:30 cutoff (HARD limit, no new entries after). "
        "Beyond 13:30, even with the fix, the cron cannot enter new positions. The current paper session is now effectively closed. "
        "(p) Actions 0 -> 0 (HOLD). Decision structurally identical to 13:20 + 13:15 + 13:10 + 13:05 + 13:00 + 12:55 + 12:50 + "
        "12:45 + 12:40 + 12:35 + 12:30 + 12:25 + 12:20 + 12:15 + 12:10 + 12:00 + 11:50."
    ),
    "risk_budget_reasoning": (
        "Risk budget = 0pct new capital at 13:25 IST. "
        "(a) No new actions this tick (HOLD). "
        "(b) Bottleneck is HTTP 400 batch size in kotak_prod_feed._fetch_option_quotes, not thesis quality. "
        "(c) Thesis remains EXCELLENT and UNCHANGED from 13:20: range regime both conf 0.7, range_pct 13:25 NIFTY 0.56% / BNF 0.68% "
        "(UNCHANGED from 13:20), VIX 11.18 calm 1.0x mult, macro quiet, monday brief risk_on preferred iron_condor, "
        "Mavis expected range [23922.84, 24258.86] still contains NIFTY 24066.85 (inside lower band by ~144pt, comfortable), "
        "BNF 57391.70 above 57300 trigger by +91.70pt (UNCHANGED from 13:20, still well above trigger). "
        "(d) Plan A iron_condor still 2/2 underlying TRIGGERED with healthy buffers: "
        "NIFTY 24066.85 GT 24020 +46.85pt (UNCHANGED from +46.65pt, still >40pt), "
        "BNF 57391.70 GT 57300 +91.70pt (UNCHANGED from 13:20). Plan B 0/2, Plan C 0/1. "
        "(e) 0pct risk budget because: (i) the order path is structurally blocked by HTTP 400, "
        "(ii) the fix window has TERMINALLY CLOSED - 5 min to 13:30 HARD limit (was 10 min at 13:20, now 5 min), "
        "(iii) no realistic path to a filled entry before 13:30 even with immediate code+restart. "
        "(f) Bias cautious does NOT increase risk_budget_pct (still 0pct) - it only changes the BIAS label. "
        "(g) Time-budget (TERMINAL): 5 min to 13:30 cutoff (HARD limit, no new entries after), "
        "1h05m to 14:30 force-square-off (N/A - 0 positions), 2h05m to 15:30 close. "
        "The HTTP 400 fix is NO LONGER ACTIONABLE for this session. "
        "The fix is still valuable for FUTURE sessions (Sep 1, Tue)."
    ),
    "candle_regime_evidence": {
        "NIFTY": {
            "confidence": 0.7,
            "regime": "range",
            "reason": (
                "range=0.56pct tight (5d per fresh yfinance 13:25) + vix=11.18 calm band 1.0x mult. "
                "Live intraday at 13:25: NIFTY 24066.85 (FLAT +0.20pt from 24066.65 at 13:20, holding above 24065). "
                "NIFTY vs brief close 24090.85 = -24.00pt gap down (NARROWED from -24.20pt at 13:20 by +0.20pt). "
                "NIFTY vs 09:30 24040 = +26.85pt. NIFTY vs 24000 round support = +66.85pt ABOVE. "
                "NIFTY vs 24020 Plan A trigger = +46.85pt ABOVE TRIGGERED, buffer UNCHANGED from +46.65pt at 13:20 (still >40pt, healthy). "
                "5d candles (trader_state yfinance last 5d, refreshed 13:25): 24219.05, 24334.55, 24207.75, 24090.85, 24067.00. "
                "Today intraday bar 2026-08-31: open 24117.55 high 24128.70 low 23993.60 close 24067.00. adx low. "
                "Range-bound, low-vol, supportive of iron condor. Thesis intact. "
                "Execution path BLOCKED by HTTP 400 batch size (18th consecutive tick of blocker, 95 min blocked). "
                "Fix window NOW TERMINAL at 5 min to 13:30 cutoff."
            ),
            "range_pct": 0.56,
            "last_close": 24067.0,
            "trend_5d": "down",
            "change_5d_pct": -0.63,
        },
        "BANKNIFTY": {
            "confidence": 0.7,
            "regime": "range",
            "reason": (
                "range=0.68pct tight (5d per fresh yfinance 13:25) + vix=11.18 calm band 1.0x mult. "
                "Live intraday at 13:25: BNF last print 57391.70 at 13:20 (no fresh print in 13:25 log tail). "
                "BNF vs brief close 57509.95 = -118.25pt gap down (UNCHANGED from 13:20). "
                "BNF vs 57300 = +91.70pt ABOVE. "
                "BNF vs 57300 Plan A trigger = +91.70pt ABOVE TRIGGERED, buffer UNCHANGED from 13:20. "
                "5d candles: 57525.95, 57514.20, 57783.75, 57509.95, 57405.80. "
                "Today intraday bar: open 57353.75 high 57576.25 low 57187.35 close 57405.80. "
                "Range-bound. Mavis plan is for NIFTY only, not BANKNIFTY - defer."
            ),
            "range_pct": 0.68,
            "last_close": 57405.8,
            "trend_5d": "flat",
            "change_5d_pct": -0.21,
        },
    },
    "macro_evidence": {
        "upcoming": [],
        "in_blackout": False,
        "interpretation": (
            "macro.upcoming is empty list, in_blackout=false, next_event_min=null. QUIET macro calendar. "
            "Monday brief macro_blackout_soon=false, macro_events_next_7d=[]. No RBI policy, Fed, or US CPI in immediate window. "
            "Macro layer is QUIET - no event-driven constraint on new entries today. "
            "The decision to HOLD is based on the order placement path being broken (HTTP 400 batch size) "
            "AND the fix window having TERMINALLY CLOSED (5 min to 13:30 cutoff), NOT on macro concerns."
        ),
    },
    "research_evidence": {
        "available": False,
        "fallback": (
            "Research PDF download still failing (kotak_research.download_latest_research_pdf:52 WARNING at 13:25). "
            "Candle+macro+VIX-only mode. No max_pain, PCR, or FII flows available. "
            "Defer to: (a) candle_regime both range conf 0.7, (b) VIX 11.18 calm 1.0x mult, "
            "(c) US S&P +0.74pct / Nasdaq +1.57pct Fri - monday_brief catalyst (5d), "
            "(d) preferred_strategies from brief = [bull_call_vertical, iron_condor] - iron condor is the preferred structure for range regime, "
            "(e) Mavis thesis engine INDEPENDENTLY fired EXECUTE_PLAN for NIFTY iron_condor at confidence 0.85 "
            "with thesis expected_move 168pt, range [23922.84, 24258.86], NIFTY spot 24066.85 inside range. "
            "No research-driven bias override needed. The decision to HOLD is based on the order placement path being broken "
            "AND the fix window having TERMINALLY CLOSED, not on research-driven bias."
        ),
    },
    "open_positions_summary": {
        "count": 0,
        "max_positions_limit": 2,
        "post_trade_count": 0,
        "max_reached": False,
        "details": [],
        "note": (
            "0 -> 0 open positions this tick (HOLD, no actions). Capital 1,09,978 INR, realized +9,978 INR. "
            "Spot evolution 13:20 -> 13:25: NIFTY +0.20pt FLAT (24066.85 vs 24066.65 at 13:20, holding above 24065), "
            "BNF last print 57391.70 at 13:20 (no fresh BNF print in 13:25 log tail). "
            "BUFFERS 13:20->13:25: NIFTY +46.85pt (was +46.65pt at 13:20, UNCHANGED by +0.20pt, still >40pt healthy), "
            "BNF +91.70pt (UNCHANGED from 13:20, still well above trigger). "
            "Plan A iron_condor still 2/2 underlying TRIGGERED with healthy buffers. "
            "ROOT CAUSE UNCHANGED: HTTP 400 still firing every 2-3 sec on _fetch_option_quotes. "
            "18th CONSECUTIVE TICK of structural blocker. 95 min of blocked execution. "
            "DUAL MAVIS ANOMALY PERSISTS: cycle=3507 + cycle=38263 in bot log tail (13:25:28 within 1.5s) - "
            "orphan/duplicate bot process. Bot-internal Mavis cycle=38263 at 13:25:28 EXECUTE_PLAN NIFTY conf=0.85 - "
            "same as 13:20/13:15/13:10 - blocked by HTTP 400. "
            "Bias UNCHANGED cautious. Decision: HOLD. "
            "FIX WINDOW NOW TERMINAL: 5 min to 13:30 cutoff (HARD limit, was 10 min at 13:20, no new entries after). "
            "The HTTP 400 fix is NO LONGER ACTIONABLE for this session. "
            "The fix is still valuable for FUTURE sessions (Sep 1, Tue)."
        ),
    },
    "tick_context": {
        "previous_decision_ist": "2026-08-31 13:20:00",
        "previous_decision_bias": "cautious",
        "previous_decision_actions_count": 0,
        "decision_changed": False,
        "decision_change_reason": (
            "13:25 IST cron tick (5 min after 13:20, 235 min into regular session). "
            "Structural decision (HOLD, 0 actions, bias cautious) UNCHANGED from 13:20 + 13:15 + 13:10 + 13:05 + 13:00 + "
            "12:55 + 12:50 + 12:45 + 12:40 + 12:35 + 12:30 + 12:25 + 12:20 + 12:15 + 12:10 + 12:00 + 11:50. "
            "(a) NO ESCALATION this tick - 12:15 escalation already surfaced the P1 to user. "
            "(b) 18th CONSECUTIVE TICK of structural HTTP 400 blocker. 95 min of blocked execution. "
            "(c) BUFFER EVOLUTION 13:20->13:25: NIFTY +46.85pt (UNCHANGED from +46.65pt, still >40pt healthy), "
            "BNF +91.70pt (UNCHANGED from 13:20, still well above trigger). Buffers still HEALTHY but the path is still BLOCKED. "
            "(d) 5d trends 13:20->13:25: NIFTY -0.63% (UNCHANGED from 13:20), BNF -0.21% (vs -0.23% at 13:20, slightly IMPROVED). "
            "(e) range_pct 13:25 refresh: NIFTY 0.56% (5d), BNF 0.68% (5d) - per fresh yfinance. UNCHANGED from 13:20. "
            "(f) FIX WINDOW NOW TERMINAL: 5 min to 13:30 cutoff (HARD limit, was 10 min at 13:20, no new entries after). "
            "This is the LAST tick where new entries are even theoretically possible. "
            "Even immediate code+restart cannot deliver a filled entry before 13:30. "
            "(g) DUAL MAVIS ANOMALY PERSISTS: cycle=3507 + cycle=38263 in bot log (13:25:28 within 1.5s) - "
            "orphan bot process pattern from AGENTS.md. "
            "(h) Telegram will dedupe (bias same, actions same, note same shape with 18th replacing 17th) - "
            "this is correct because the user has already been alerted and the situation is structurally unchanged. "
            "(i) Bot-internal Mavis cycle=38263 at 13:25:28 EXECUTE_PLAN NIFTY iron_condor conf=0.85 - same as 13:20/13:15 - blocked by HTTP 400. "
            "(j) 0 open positions. (k) User-actionable paths unchanged from 13:20."
        ),
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
        "log_tail_evidence_bot_alive_but_path_broken_http400_dual_mavis_fix_window_now_terminal": (
            "13:25:02.292 WARNING _fetch_option_quotes:560 HTTP 400 | "
            "13:25:04.541 WARNING _fetch_option_quotes:560 HTTP 400 | "
            "13:25:06.900 WARNING _fetch_option_quotes:560 HTTP 400 | "
            "13:25:09.199 WARNING _fetch_option_quotes:560 HTTP 400 | "
            "13:25:11.501 WARNING _fetch_option_quotes:560 HTTP 400 | "
            "13:25:13.809 WARNING _fetch_option_quotes:560 HTTP 400 | "
            "13:25:16.207 WARNING _fetch_option_quotes:560 HTTP 400 | "
            "13:25:18.511 WARNING _fetch_option_quotes:560 HTTP 400 | "
            "13:25:19.305 LiveKotak heartbeat: authed=True subscribed=48 latest=48 tick_count=168600 | "
            "13:25:20.874 WARNING _fetch_option_quotes:560 HTTP 400 | "
            "13:25:23.177 WARNING _fetch_option_quotes:560 HTTP 400 | "
            "13:25:25.437 WARNING _fetch_option_quotes:560 HTTP 400 | "
            "13:25:27.779 WARNING _fetch_option_quotes:560 HTTP 400 | "
            "13:25:28.048 SCAN cycle=38263 NIFTY spot=24066.85 atm=24050 opts=18 regime=range conf=0.40 | "
            "13:25:28.049 MAVIS cycle=38263 NIFTY EXECUTE_PLAN: iron_condor confidence=0.85"
        ),
    },
    "actions_count": 0,
    "timestamp": "2026-08-31T07:55:00Z",
}


def main():
    with open(FP, "r", encoding="utf-8") as f:
        data = json.load(f)

    old_last = data.get("last_decision", {})

    data["last_decision"] = NEW_DECISION
    data["timestamp"] = "2026-08-31T07:55:00Z"
    data["call_count_today"] = data.get("call_count_today", 0) + 1

    history = data.get("history", [])
    if old_last and "ist_time" in old_last:
        if not any(h.get("ist_time") == old_last.get("ist_time") for h in history):
            history.insert(0, old_last)
            data["history"] = history

    with open(FP, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"OK: call_count_today={data['call_count_today']}, history_len={len(data.get('history', []))}")
    print(f"  last_decision.ist_time={data['last_decision']['ist_time']}")
    print(f"  last_decision.bias={data['last_decision']['bias']}")
    print(f"  last_decision.actions={data['last_decision']['actions']}")
    print(f"  last_decision.note={data['last_decision']['note']}")


if __name__ == "__main__":
    main()
