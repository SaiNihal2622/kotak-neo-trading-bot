"""
12:55 IST cron tick — update brain_state.json last_decision.
12th consecutive tick of HTTP 400 structural blocker. Buffers recovered.
Time-budget CRITICAL: 35 min to 13:30 cutoff.
"""
import json
from datetime import datetime, timezone, timedelta

path = r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json"
with open(path, encoding="utf-8") as f:
    d = json.load(f)

ist = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=5, minutes=30)))
ist_str = ist.strftime("%Y-%m-%d %H:%M:%S")
ts_utc = ist.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

last_dec = {
    "ts": ts_utc,
    "ist_time": ist_str,
    "bias": "cautious",
    "source": "mavis",
    "max_positions": 0,
    "actions": [],
    "note": "p1_blocker_http400_batch_size_12th_consecutive_tick_buffers_recovered_both_above_50pt_dual_mavis_persists_37903_plus_3147_35min_to_cutoff",
    "decision_summary": (
        "12:55 IST cron tick (5 min after 12:50, 205 min into regular session, market_session=regular). "
        "HOLD, 0 actions, bias UNCHANGED at cautious. (a) ROOT CAUSE UNCHANGED: HTTP 400 'Please set the "
        "Neo symbol max value to 50' still firing every 2-3 sec on kotak_bot/data/kotak_prod_feed.py:"
        "_fetch_option_quotes:560 (bot log tail 12:55:14 to 12:55:26 = 6 warnings in 12s window). "
        "12th CONSECUTIVE TICK of structural blocker (11:50, 12:00, 12:10, 12:15, 12:20, 12:25, 12:30, "
        "12:35, 12:40, 12:45, 12:50, 12:55). 65 min of blocked execution since first identification at "
        "11:50. (b) DUAL MAVIS ANOMALY PERSISTS: cycle=37903 (orphan, +60 from 12:50 37843) AND "
        "cycle=3147 (current, +60 from 12:50 3087). Both firing EXECUTE_PLAN NIFTY iron_condor conf=0.85 "
        "- both blocked by HTTP 400. Orphan bot process pattern from AGENTS.md. (c) Live spot evolution "
        "12:50 -> 12:55: NIFTY 24070.65 -> 24074.80 +4.15pt (GREEN continuation); BNF 57333.85 -> "
        "57356.50 +22.65pt (GREEN bounce, recovered). (d) POSITIVE: BUFFERS RECOVERED BOTH ABOVE 50pt: "
        "NIFTY 24074.80 GT 24020 +54.80pt above (IMPROVED from +50.65pt at 12:50 by +4.15pt), BNF "
        "57356.50 GT 57300 +56.50pt above (RECOVERED from +33.85pt at 12:50 by +22.65pt - back above 50pt). "
        "Plan A iron_condor still 2/2 underlying TRIGGERED with healthy buffers. (e) Plan B "
        "bear_put_vertical 0/2 (NIFTY 24074.80 NOT < 24000, BNF 57356.50 NOT < 57250). Plan C "
        "short_strangle NOT triggered (VIX 11.17 not > 12). (f) Bot-internal Mavis cycle=3147 at 12:55:20 "
        "EXECUTE_PLAN NIFTY iron_condor conf=0.85 - same as 12:50/12:45 - blocked by HTTP 400. The second "
        "Mavis at cycle=37903 also firing EXECUTE_PLAN. Both blocked. (g) VIX 11.1725 (calm, 1.0x mult). "
        "Macro quiet, in_blackout=false, upcoming=[]. (h) 5d candle regime: NIFTY range conf 0.7, BNF "
        "range conf 0.7 - INTACT. (i) Research PDF still failing - candle+macro+VIX-only mode. (j) 0 open "
        "positions. Capital Rs.1,09,978, realized +Rs.9,978. (k) Bias UNCHANGED cautious - 12:15 "
        "escalation already surfaced P1. Re-escalating would be misleading. (l) TIME-BUDGET (CRITICAL): "
        "35 min to 13:30 cutoff, 1h35m to 14:30 force-square-off, 2h35m to 15:30 close. The fix is needed "
        "in by ~13:00 (5 min from now) to save the paper session. Beyond 13:30 the cron cannot enter new "
        "positions even with the fix."
    ),
    "rationale": (
        "12:55 IST cron tick (5 min after 12:50, market_session=regular, 205 min into regular session). "
        "HOLD, 0 actions, bias UNCHANGED cautious. (a) Structural blocker UNCHANGED: HTTP 400 'Please set "
        "the Neo symbol max value to 50' still firing every 2-3 sec on kotak_bot/data/kotak_prod_feed.py:"
        "_fetch_option_quotes:560. 6 warnings in the 12s window 12:55:14 to 12:55:26 in the bot log "
        "tail. The execution path for any new options order (iron condor pricing, Mavis EXECUTE_PLAN, "
        "post-decision quote fetch) is BLOCKED. (b) 12th CONSECUTIVE TICK of the same structural blocker "
        "(11:50, 12:00, 12:10, 12:15, 12:20, 12:25, 12:30, 12:35, 12:40, 12:45, 12:50, 12:55). 65 min of "
        "blocked execution. (c) DUAL MAVIS ANOMALY PERSISTS: cycle=37903 (orphan, +60 from 12:50 37843) "
        "AND cycle=3147 (current, +60 from 12:50 3087) within the same minute. Both +60 in 5 min = 1 "
        "cycle per 5 sec. The 37903 counter is anomalous - orphan bot process from AGENTS.md 'Orphan bot "
        "processes' known-issue. (d) POSITIVE EVOLUTION 12:50 -> 12:55: NIFTY +4.15pt GREEN continuation "
        "(24070.65 -> 24074.80), BNF +22.65pt GREEN bounce (57333.85 -> 57356.50). Plan A iron_condor "
        "still 2/2 underlying TRIGGERED and BUFFERS RECOVERED: NIFTY buffer +54.80pt (was +50.65pt, "
        "IMPROVED by +4.15pt, still >50pt), BNF buffer +56.50pt (was +33.85pt, RECOVERED by +22.65pt - "
        "back above 50pt for the first time since 12:30). (e) Plan B bear_put_vertical 0/2. Plan C "
        "short_strangle NOT triggered. (f) Bot-internal Mavis cycle=3147 EXECUTE_PLAN NIFTY iron_condor "
        "conf=0.85 (NIFTY spot 24090.85 inside expected range [23922.84, 24258.86], thesis expected_move "
        "168pt) - same as 12:50/12:45/12:40 - blocked by HTTP 400. (g) VIX 11.1725 calm 1.0x mult, no IV "
        "expansion. Macro quiet. (h) Candle regime: NIFTY range conf 0.7 (range_pct 0.56%), BNF range "
        "conf 0.7 (range_pct 0.68%). 5d trend NIFTY -0.59% DOWN (IMPROVED from -0.61% at 12:50, NIFTY "
        "last_close 24074.95 vs 24070.90 at 12:50), BNF -0.29% FLAT (IMPROVED from -0.32% at 12:50, BNF "
        "last_close 57359.95 vs 57340.85 at 12:50). Thesis INTACT. (i) Research unavailable. (j) 0 open "
        "positions, capital Rs.1,09,978, realized +Rs.9,978. (k) NOT re-issuing iron_condor action "
        "because: (i) the order path is structurally blocked by HTTP 400, (ii) re-issuing would create a "
        "12th consumed action with no fill, (iii) the fix is a CODE CHANGE + bot restart, not a cron "
        "decision, (iv) buffers are now healthy (both >50pt) but the bot still cannot fetch quotes to "
        "validate premiums. (l) Bias UNCHANGED cautious. (m) USER-ACTIONABLE PATHS UNCHANGED: (i) HTTP 400 "
        "fix = chunk symbols into <=50 batches in kotak_bot/data/kotak_prod_feed.py::_fetch_option_quotes "
        "around line 560, (ii) nssm restart KotakBotPaper to pick up new code, (iii) orphan bot process "
        "needs admin UAC for taskkill /F /T /PID, (iv) investigate the dual Mavis cycle anomaly. (n) "
        "Time-budget (CRITICAL): 35 min to 13:30 cutoff, 1h35m to 14:30 force-square-off, 2h35m to 15:30 "
        "close. The fix is needed in by ~13:00 (5 min from now) to save the paper session. Beyond 13:30, "
        "even with the fix, the cron cannot enter new positions. (o) Actions 0 -> 0 (HOLD). Decision "
        "structurally identical to 12:50 + 12:45 + 12:40."
    ),
    "risk_budget_reasoning": (
        "Risk budget = 0pct new capital at 12:55 IST. (a) No new actions this tick (HOLD). (b) Bottleneck "
        "is HTTP 400 batch size in kotak_prod_feed._fetch_option_quotes, not thesis quality. (c) Thesis "
        "remains EXCELLENT in isolation: range regime both conf 0.7, VIX 11.1725 calm 1.0x mult, macro "
        "quiet, monday brief risk_on preferred iron_condor, Mavis expected range [23922.84, 24258.86] "
        "still contains NIFTY 24074.80 (inside lower band by ~152pt, comfortable), BNF 57356.50 above "
        "57300 trigger by +56.50pt (RECOVERED from +33.85pt at 12:50 by +22.65pt). (d) Plan A iron_condor "
        "still 2/2 underlying TRIGGERED with BUFFERS RECOVERED: NIFTY 24074.80 GT 24020 +54.80pt, BNF "
        "57356.50 GT 57300 +56.50pt - both ABOVE 50pt. Plan B 0/2, Plan C 0/2. (e) 0pct risk budget "
        "because the order path is structurally blocked by HTTP 400. (f) Once the HTTP 400 fix ships and "
        "a bot restart picks it up, the cron can re-issue Plan A NIFTY iron condor at the next tick - IF "
        "both NIFTY and BNF buffers are still > their respective triggers. (g) Bias cautious does NOT "
        "increase risk_budget_pct (still 0pct) - it only changes the BIAS label. (h) Time-budget "
        "(CRITICAL): 35 min to 13:30 cutoff, 1h35m to 14:30 force-square-off, 2h35m to 15:30 close. The "
        "fix is needed in by ~13:00 (5 min from now) to save the paper session. The 13:30 cutoff is a "
        "HARD limit."
    ),
    "candle_regime_evidence": {
        "NIFTY": {
            "confidence": 0.7,
            "regime": "range",
            "reason": (
                "range=0.56pct tight (5d per fresh yfinance) + vix=11.1725 calm band 1.0x mult. Live "
                "intraday at 12:55: NIFTY 24074.80 (GREEN +4.15pt from 24070.65 at 12:50, slight "
                "continuation). NIFTY vs brief close 24090.85 = -16.05pt gap down (NARROWED from -20.20pt "
                "at 12:50 by +4.15pt). NIFTY vs 09:30 24040 = +34.80pt. NIFTY vs 24000 round support = "
                "+74.80pt ABOVE. NIFTY vs 24020 Plan A trigger = +54.80pt ABOVE TRIGGERED, buffer IMPROVED "
                "from +50.65pt at 12:50 by +4.15pt (still >50pt). 5d candles (trader_state yfinance last "
                "5d, refreshed 12:55): 24219.05, 24334.55, 24207.75, 24090.85, 24074.95. Today intraday "
                "bar 2026-08-31: open 24117.55 high 24128.70 low 23993.60 close 24074.95. adx low. "
                "Range-bound, low-vol, supportive of iron condor. Thesis intact but execution path "
                "blocked by HTTP 400 batch size (12th consecutive tick of blocker, 65 min blocked)."
            ),
            "range_pct": 0.56,
            "last_close": 24074.95,
            "trend_5d": "down",
            "change_5d_pct": -0.59,
        },
        "BANKNIFTY": {
            "confidence": 0.7,
            "regime": "range",
            "reason": (
                "range=0.68pct tight (5d per fresh yfinance) + vix=11.1725 calm band 1.0x mult. Live "
                "intraday at 12:55: BNF 57356.50 (GREEN +22.65pt from 57333.85 at 12:50, RECOVERED bounce). "
                "BNF vs brief close 57509.95 = -153.45pt gap down (NARROWED from -176.10pt at 12:50 by "
                "+22.65pt). BNF vs 57300 = +56.50pt ABOVE - RECOVERED above 50pt for first time since "
                "12:30 (was +33.85pt at 12:50). 5d candles: 57525.95, 57514.20, 57783.75, 57509.95, "
                "57359.95. Today intraday bar: open 57353.75 high 57576.25 low 57187.35 close 57359.95. "
                "Range-bound. Mavis plan is for NIFTY only, not BANKNIFTY - defer."
            ),
            "range_pct": 0.68,
            "last_close": 57359.95,
            "trend_5d": "flat",
            "change_5d_pct": -0.29,
        },
    },
    "macro_evidence": {
        "upcoming": [],
        "in_blackout": False,
        "interpretation": (
            "macro.upcoming is empty list, in_blackout=false, next_event_min=null. QUIET macro calendar. "
            "Monday brief macro_blackout_soon=false, macro_events_next_7d=[]. No RBI policy, Fed, or US "
            "CPI in immediate window. Macro layer is QUIET - no event-driven constraint on new entries "
            "today. The decision to HOLD is based on the order placement path being broken (HTTP 400 "
            "batch size), not on macro concerns."
        ),
    },
    "research_evidence": {
        "available": False,
        "fallback": (
            "Research PDF download still failing (kotak_research.download_latest_research_pdf:52 WARNING "
            "at 12:55). Candle+macro+VIX-only mode. No max_pain, PCR, or FII flows available. Defer to: "
            "(a) candle_regime both range conf 0.7, (b) VIX 11.1725 calm 1.0x mult, (c) US S&P +0.74pct "
            "/ Nasdaq +1.57pct Fri - monday_brief catalyst (5d), (d) preferred_strategies from brief = "
            "[bull_call_vertical, iron_condor] - iron condor is the preferred structure for range regime, "
            "(e) Mavis thesis engine INDEPENDENTLY fired EXECUTE_PLAN for NIFTY iron_condor at "
            "confidence 0.85 with thesis expected_move 168pt, range [23922.84, 24258.86], NIFTY spot "
            "24090.85 inside range. No research-driven bias override needed. The decision to HOLD is "
            "based on the order placement path being broken, not on research-driven bias."
        ),
    },
    "open_positions_summary": {
        "count": 0,
        "max_positions_limit": 2,
        "post_trade_count": 0,
        "max_reached": False,
        "details": [],
        "note": (
            "0 -> 0 open positions this tick (HOLD, no actions). Capital 1,09,978 INR, realized +9,978 "
            "INR. Spot evolution 12:50 -> 12:55: NIFTY +4.15pt GREEN continuation (24074.80 vs 24070.65 "
            "at 12:50), BNF +22.65pt GREEN bounce (57356.50 vs 57333.85 at 12:50). BUFFERS RECOVERED "
            "from 12:50: NIFTY buffer +54.80pt (was +50.65pt, IMPROVED by +4.15pt, still >50pt), BNF "
            "buffer +56.50pt (was +33.85pt, RECOVERED by +22.65pt - BACK ABOVE 50pt for first time since "
            "12:30). Plan A iron_condor still 2/2 underlying TRIGGERED with healthy buffers. ROOT CAUSE "
            "UNCHANGED: HTTP 400 still firing every 2-3 sec on _fetch_option_quotes. 12th CONSECUTIVE "
            "TICK of structural blocker. 65 min of blocked execution. DUAL MAVIS ANOMALY PERSISTS: "
            "cycle=37903 + cycle=3147 in bot log tail (12:55:17 and 12:55:20) - orphan/duplicate bot "
            "process. Bot-internal Mavis cycle=3147 at 12:55:20 EXECUTE_PLAN NIFTY conf=0.85 - same as "
            "12:50 - blocked by HTTP 400. BANKNIFTY BLOCK at 12:55:20. Bias UNCHANGED cautious. "
            "Decision: HOLD. After HTTP 400 fix (chunk symbols into <=50 batches) + bot restart, cron "
            "can re-issue Plan A NIFTY iron_condor - IF both buffers still > triggers. Time-budget "
            "concern (CRITICAL): 35 min to 13:30 cutoff. If fix not in by ~13:00 (5 min from now), the "
            "entire paper session is wasted. Beyond 13:30 the bot no-new-entries rule kicks in."
        ),
    },
    "tick_context": {
        "previous_decision_ist": "2026-08-31 12:50:00",
        "previous_decision_bias": "cautious",
        "previous_decision_actions_count": 0,
        "decision_changed": False,
        "decision_change_reason": (
            "12:55 IST cron tick (5 min after 12:50, 205 min into regular session). Structural decision "
            "(HOLD, 0 actions, bias cautious) UNCHANGED from 12:50 + 12:45 + 12:40 + 12:35. (a) NO "
            "ESCALATION this tick - 12:15 escalation already surfaced the P1 to user. (b) 12th CONSECUTIVE "
            "TICK of structural HTTP 400 blocker. 65 min of blocked execution. (c) POSITIVE EVOLUTION "
            "12:50->12:55: BUFFERS RECOVERED BOTH ABOVE 50pt - NIFTY +54.80pt (was +50.65pt), BNF "
            "+56.50pt (was +33.85pt, RECOVERED). (d) DUAL MAVIS ANOMALY PERSISTS: cycle=37903 + cycle=3147 "
            "in bot log (12:55:17 and 12:55:20) - orphan bot process pattern from AGENTS.md. (e) Telegram "
            "will dedupe (bias same, actions same, note same shape with '12th' replacing '11th') - this is "
            "correct because the user has already been alerted and the situation is structurally "
            "unchanged. (f) Bot-internal Mavis cycle=3147 at 12:55:20 EXECUTE_PLAN NIFTY iron_condor "
            "conf=0.85 - same as 12:50 - blocked by HTTP 400. (g) 0 open positions. (h) User-actionable "
            "paths unchanged. (i) Time-budget (CRITICAL): 35 min to 13:30 cutoff, 1h35m to 14:30 "
            "force-square-off, 2h35m to 15:30 close. If fix not in by ~13:00 (5 min from now) the entire "
            "paper session is wasted."
        ),
        "monday_brief_summary": {
            "regime_hint": "risk_on",
            "india_open_gap_signal": "gap_up",
            "recommended_posture": "normal",
            "max_risk_per_trade_pct": 2.0,
            "skip_first_30min_per_brief": False,
            "skip_first_30min_per_brief_rationale": (
                "gap_up -> skip 30min (brief internal contradiction: explicit flag=false but rationale "
                "recommends skip)"
            ),
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
        "log_tail_evidence_bot_alive_but_path_broken_http400_dual_mavis": (
            "12:55:14.905 WARNING _fetch_option_quotes:560 HTTP 400 | 12:55:17.141 WARNING "
            "_fetch_option_quotes:560 HTTP 400 | 12:55:17.200 SCAN cycle=37903 NIFTY spot=24073.45 "
            "atm=24050 opts=18 regime=range conf=0.40 adx=0.5 mom=+0.00 | 12:55:17.201 MAVIS cycle=37903 "
            "NIFTY | EXECUTE_PLAN: iron_condor confidence=0.85 reason=mavis_override: NIFTY spot 24090.85 "
            "inside expected range [23922.84, 24258.86] (thesis expected_move 168pt). Sell wings | "
            "12:55:17.281 SCAN cycle=37903 BANKNIFTY spot=57359.25 atm=57400 opts=18 regime=range "
            "conf=0.40 adx=0.4 mom=+0.00 | 12:55:17.296 MAVIS cycle=37903 BANKNIFTY | Mavis plan is for "
            "NIFTY, not BANKNIFTY - falling through to template | 12:55:18.892 LiveKotak heartbeat: "
            "authed=True subscribed=48 latest=48 tick_count=146746 | 12:55:19.410 WARNING "
            "_fetch_option_quotes:560 HTTP 400 | 12:55:20.517 SCAN cycle=3147 NIFTY spot=24074.80 "
            "atm=24050 opts=18 regime=range conf=0.40 adx=0.2 mom=-0.00 | 12:55:20.518 MAVIS cycle=3147 "
            "NIFTY | EXECUTE_PLAN: iron_condor confidence=0.85 reason=mavis_override: NIFTY spot 24090.85 "
            "inside expected range [23922.84, 24258.86] (thesis expected_move 168pt). Sell wings | "
            "12:55:20.559 SCAN cycle=3147 BANKNIFTY spot=57356.50 atm=57400 opts=18 regime=range "
            "conf=0.40 adx=1.0 mom=-0.00 | 12:55:20.560 MAVIS cycle=3147 BANKNIFTY | BLOCK: Mavis plan "
            "is for NIFTY, not BANKNIFTY | 12:55:21.619 WARNING _fetch_option_quotes:560 HTTP 400 | "
            "12:55:23.854 WARNING _fetch_option_quotes:560 HTTP 400 | 12:55:26.082 WARNING "
            "_fetch_option_quotes:560 HTTP 400"
        ),
    },
    "actions_count": 0,
    "timestamp": ts_utc,
}

d["last_decision"] = last_dec
d["timestamp"] = ts_utc
d["last_updated_ist"] = ist_str
d["call_count_today"] = d.get("call_count_today", 0) + 1

with open(path, "w", encoding="utf-8") as f:
    json.dump(d, f, ensure_ascii=False, indent=2)

print("OK last_decision updated")
print("ist_time:", ist_str, "ts_utc:", ts_utc)
print("bias:", last_dec["bias"], "actions:", len(last_dec["actions"]))
print("note:", last_dec["note"])
print("call_count_today:", d["call_count_today"])
print("history_len:", len(d.get("history", [])))
