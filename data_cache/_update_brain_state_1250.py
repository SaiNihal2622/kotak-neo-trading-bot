#!/usr/bin/env python
"""Update brain_state.json last_decision block for 12:50 IST cron tick."""
import json
from pathlib import Path

p = Path(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json")
data = json.loads(p.read_text(encoding="utf-8"))

# New 12:50 decision block
new_decision = {
    "ts": "2026-08-31T07:20:00Z",
    "ist_time": "2026-08-31 12:50:00",
    "bias": "cautious",
    "source": "mavis",
    "max_positions": 0,
    "actions": [],
    "note": "p1_blocker_http400_batch_size_11th_consecutive_tick_dual_mavis_cycle_anomaly_37843_plus_3087",
    "decision_summary": "12:50 IST cron tick (5 min after 12:45, 200 min into regular session, market_session=regular). HOLD, 0 actions, bias UNCHANGED at cautious. (a) ROOT CAUSE UNCHANGED: HTTP 400 'Please set the Neo symbol max value to 50' still firing every 2-3 sec on kotak_bot/data/kotak_prod_feed.py:_fetch_option_quotes:560 (bot log tail 12:50:16 to 12:50:33 = 6 warnings in 17s window). 11th CONSECUTIVE TICK of structural blocker (11:50, 12:00, 12:10, 12:15, 12:20, 12:25, 12:30, 12:35, 12:40, 12:45, 12:50). 60 min of blocked execution since first identification at 11:50. (b) DUAL MAVIS ANOMALY PERSISTS from 12:45: cycle=37843 (older/orphan) AND cycle=3087 (current bot Mavis, +60 from 12:45's 3027, consistent with 5-min delta). Orphan bot process pattern from AGENTS.md. Both Mavis instances still firing EXECUTE_PLAN NIFTY iron_condor conf=0.85 — both blocked by HTTP 400. (c) Live spot evolution 12:45 -> 12:50: NIFTY 24066.85 -> 24070.65 +3.80pt (GREEN bounce, slight recovery); BNF 57347.45 -> 57333.85 -13.60pt (RED continuation, dropped further below 57350). (d) Plan A iron_condor still 2/2 underlying TRIGGERED but BUFFERS DIVERGED: NIFTY 24070.65 GT 24020 +50.65pt above (buffer IMPROVED from +46.85pt at 12:45 by +3.80pt, now >50pt), BNF 57333.85 GT 57300 +33.85pt above (buffer REDUCED from +47.45pt at 12:45 by -13.60pt, still <50pt for second consecutive tick — approaching trigger rapidly). (e) Bot-internal Mavis cycle=3087 at 12:50:19 EXECUTE_PLAN NIFTY iron_condor conf=0.85 — same as 12:45/12:40 — blocked by HTTP 400. The second Mavis at cycle=37843 is also firing EXECUTE_PLAN. Both blocked. (f) VIX 11.1625 (calm, 1.0x mult). Macro quiet, in_blackout=false, upcoming=[]. (g) 5d candle regime: NIFTY range conf 0.7, BNF range conf 0.7 — INTACT. (h) Research PDF still failing — candle+macro+VIX-only mode. (i) 0 open positions. Capital Rs.1,09,978, realized +Rs.9,978. (j) Bias UNCHANGED cautious — 12:15 escalation already surfaced P1. Re-escalating would be misleading. (k) Decision structurally identical to 12:45 + 12:40. (l) TIME-BUDGET (CRITICAL): 40 min to 13:30 cutoff, 1h40m to 14:30 force-square-off, 2h40m to 15:30 close. The fix is needed in by ~13:00 (10 min from now) to save the paper session. Beyond 13:30 the cron cannot enter new positions even with the fix.",
    "rationale": "12:50 IST cron tick (5 min after 12:45, market_session=regular, 200 min into regular session). HOLD, 0 actions, bias UNCHANGED cautious. (a) Structural blocker UNCHANGED: HTTP 400 'Please set the Neo symbol max value to 50' still firing every 2-3 sec on kotak_bot/data/kotak_prod_feed.py:_fetch_option_quotes:560. 6 warnings in the 17s window 12:50:16 to 12:50:33 in the bot log tail. The execution path for any new options order (iron condor pricing, Mavis EXECUTE_PLAN, post-decision quote fetch) is BLOCKED. (b) 11th CONSECUTIVE TICK of the same structural blocker (11:50, 12:00, 12:10, 12:15, 12:20, 12:25, 12:30, 12:35, 12:40, 12:45, 12:50). 60 min of blocked execution. (c) DUAL MAVIS ANOMALY PERSISTS: cycle=37843 (orphan) AND cycle=3087 (current, +60 from 12:45's 3027) within the same minute. 3027 -> 3087 = +60 in 5 min, consistent with 1 cycle per 5 sec. The 37843 counter is anomalous — orphan bot process from AGENTS.md 'Orphan bot processes' known-issue. The 12:40 log did NOT show this dual cycle, so the divergence started between 12:40 and 12:45. (d) Live spot evolution 12:45 -> 12:50: NIFTY +3.80pt GREEN bounce (24066.85 -> 24070.65), BNF -13.60pt RED continuation (57347.45 -> 57333.85). Plan A iron_condor still 2/2 underlying TRIGGERED but BUFFERS DIVERGED: NIFTY buffer IMPROVED +50.65pt (back above 50pt), BNF buffer REDUCED +33.85pt (now <50pt for second tick — approaching 57300 trigger). (e) Plan B bear_put_vertical still 0/2 (NIFTY 24070.65 NOT < 24000, BNF 57333.85 NOT < 57250). Plan C short_strangle NOT triggered (VIX 11.1625 not > 12). (f) Bot-internal Mavis cycle=3087 EXECUTE_PLAN NIFTY iron_condor conf=0.85 (NIFTY spot 24090.85 inside expected range [23922.84, 24258.86], thesis expected_move 168pt) — same as 12:45/12:40 — blocked by HTTP 400. The second Mavis at cycle=37843 is also firing EXECUTE_PLAN. Both blocked. (g) VIX 11.1625 calm 1.0x mult, no IV expansion. Macro quiet, in_blackout=false, upcoming=[]. (h) Candle regime: NIFTY range conf 0.7 (range_pct 0.56%), BNF range conf 0.7 (range_pct 0.68%). 5d trend NIFTY -0.61% DOWN (improved from -0.63% at 12:45), BNF -0.32% FLAT. Thesis INTACT. (i) Research unavailable. (j) 0 open positions, capital Rs.1,09,978, realized +Rs.9,978. (k) NOT re-issuing iron_condor action because: (i) the order path is structurally blocked by HTTP 400, (ii) re-issuing would create a 12th consumed action with no fill, (iii) the fix is a CODE CHANGE + bot restart, not a cron decision, (iv) NIFTY buffer improving but BNF buffer deteriorating (now +33.85pt). (l) Bias UNCHANGED cautious. (m) USER-ACTIONABLE PATHS UNCHANGED: (i) HTTP 400 fix = chunk symbols into <=50 batches in kotak_bot/data/kotak_prod_feed.py::_fetch_option_quotes around line 560, (ii) nssm restart KotakBotPaper to pick up new code, (iii) orphan bot process needs admin UAC for taskkill /F /T /PID, (iv) investigate the dual Mavis cycle anomaly. (n) Time-budget (CRITICAL): 40 min to 13:30 cutoff, 1h40m to 14:30 force-square-off, 2h40m to 15:30 close. The fix is needed in by ~13:00 (10 min from now) to save the paper session. Beyond 13:30, even with the fix, the cron cannot enter new positions. (o) Actions 0 -> 0 (HOLD). Decision structurally identical to 12:45 + 12:40.",
    "risk_budget_reasoning": "Risk budget = 0pct new capital at 12:50 IST. (a) No new actions this tick (HOLD). (b) Bottleneck is HTTP 400 batch size in kotak_prod_feed._fetch_option_quotes, not thesis quality. (c) Thesis remains EXCELLENT in isolation: range regime both conf 0.7, VIX 11.1625 calm 1.0x mult, macro quiet, monday brief risk_on preferred iron_condor, Mavis expected range [23922.84, 24258.86] still contains NIFTY 24070.65 (inside lower band by ~148pt, comfortable), BNF 57333.85 above 57300 trigger by +33.85pt (REDUCED from +47.45pt at 12:45 by -13.60pt, still above trigger but deteriorating). (d) Plan A iron_condor still 2/2 underlying TRIGGERED (NIFTY 24070.65 GT 24020 +50.65pt, BNF 57333.85 GT 57300 +33.85pt) — BUFFERS DIVERGED: NIFTY IMPROVED to +50.65pt (back above 50pt), BNF REDUCED to +33.85pt (second tick <50pt — approaching trigger rapidly). Plan B 0/2, Plan C 0/2. (e) 0pct risk budget because the order path is structurally blocked by HTTP 400. (f) Once the HTTP 400 fix ships and a bot restart picks it up, the cron can re-issue Plan A NIFTY iron condor at the next tick — IF both NIFTY and BNF buffers are still > their respective triggers. (g) Bias cautious does NOT increase risk_budget_pct (still 0pct) — it only changes the BIAS label. (h) Time-budget (CRITICAL): 40 min to 13:30 cutoff, 1h40m to 14:30 force-square-off, 2h40m to 15:30 close. The fix is needed in by ~13:00 (10 min from now) to save the paper session. The 13:30 cutoff is a HARD limit: the cron will HOLD on all subsequent ticks even if the HTTP 400 is fixed, because the bot's no-new-entries rule kicks in.",
    "candle_regime_evidence": {
        "NIFTY": {
            "confidence": 0.7,
            "regime": "range",
            "reason": "range=0.56pct tight (5d per fresh yfinance) + vix=11.1625 calm band 1.0x mult. Live intraday at 12:50: NIFTY 24070.65 (GREEN +3.80pt from 24066.85 at 12:45, slight recovery). NIFTY vs brief close 24090.85 = -20.20pt gap down (NARROWED from -24.00pt at 12:45 by +3.80pt). NIFTY vs 09:30 24040 = +30.65pt. NIFTY vs 24000 round support = +70.65pt ABOVE. NIFTY vs 24020 Plan A trigger = +50.65pt ABOVE TRIGGERED, buffer IMPROVED from +46.85pt at 12:45 by +3.80pt (back above 50pt). 5d candles (trader_state yfinance last 5d, refreshed 12:50): 24219.05, 24334.55, 24207.75, 24090.85, 24070.90. Today intraday bar 2026-08-31: open 24117.55 high 24128.70 low 23993.60 close 24070.90. adx low. Range-bound, low-vol, supportive of iron condor. Thesis intact but execution path blocked by HTTP 400 batch size (11th consecutive tick of blocker, 60 min blocked).",
            "range_pct": 0.56,
            "last_close": 24070.9,
            "trend_5d": "down",
            "change_5d_pct": -0.61
        },
        "BANKNIFTY": {
            "confidence": 0.7,
            "regime": "range",
            "reason": "range=0.68pct tight (5d per fresh yfinance) + vix=11.1625 calm band 1.0x mult. Live intraday at 12:50: BNF 57333.85 (RED -13.60pt from 57347.45 at 12:45, continuing down). BNF vs brief close 57509.95 = -176.10pt gap down (WIDENED from -162.50pt at 12:45 by -13.60pt). BNF vs 57300 = +33.85pt ABOVE — approaching trigger, <50pt buffer for second consecutive tick. 5d candles: 57525.95, 57514.20, 57783.75, 57509.95, 57340.85. Today intraday bar: open 57353.75 high 57576.25 low 57187.35 close 57340.85. Range-bound. Mavis plan is for NIFTY only, not BANKNIFTY — defer.",
            "range_pct": 0.68,
            "last_close": 57340.85,
            "trend_5d": "flat",
            "change_5d_pct": -0.32
        }
    },
    "macro_evidence": {
        "upcoming": [],
        "in_blackout": False,
        "interpretation": "macro.upcoming is empty list, in_blackout=false, next_event_min=null. QUIET macro calendar. Monday brief macro_blackout_soon=false, macro_events_next_7d=[]. No RBI policy, Fed, or US CPI in immediate window. Macro layer is QUIET — no event-driven constraint on new entries today. The decision to HOLD is based on the order placement path being broken (HTTP 400 batch size), not on macro concerns."
    },
    "research_evidence": {
        "available": False,
        "fallback": "Research PDF download still failing (kotak_research.download_latest_research_pdf:52 WARNING at 12:50). Candle+macro+VIX-only mode. No max_pain, PCR, or FII flows available. Defer to: (a) candle_regime both range conf 0.7, (b) VIX 11.1625 calm 1.0x mult, (c) US S&P +0.74pct / Nasdaq +1.57pct Fri — monday_brief catalyst (5d), (d) preferred_strategies from brief = [bull_call_vertical, iron_condor] — iron condor is the preferred structure for range regime, (e) Mavis thesis engine INDEPENDENTLY fired EXECUTE_PLAN for NIFTY iron_condor at confidence 0.85 with thesis expected_move 168pt, range [23922.84, 24258.86], NIFTY spot 24090.85 inside range. No research-driven bias override needed. The decision to HOLD is based on the order placement path being broken, not on research-driven bias."
    },
    "open_positions_summary": {
        "count": 0,
        "max_positions_limit": 2,
        "post_trade_count": 0,
        "max_reached": False,
        "details": [],
        "note": "0 -> 0 open positions this tick (HOLD, no actions). Capital 1,09,978 INR, realized +9,978 INR. Spot evolution 12:45 -> 12:50: NIFTY +3.80pt GREEN (24070.65 vs 24066.85 at 12:45), BNF -13.60pt RED (57333.85 vs 57347.45 at 12:45). BUFFERS DIVERGED from 12:45: NIFTY buffer +50.65pt (was +46.85pt, IMPROVED back above 50pt), BNF buffer +33.85pt (was +47.45pt, REDUCED — second tick <50pt, approaching 57300 trigger). Plan A iron_condor still 2/2 underlying TRIGGERED. ROOT CAUSE UNCHANGED: HTTP 400 still firing every 2-3 sec on _fetch_option_quotes. 11th CONSECUTIVE TICK of structural blocker. 60 min of blocked execution. DUAL MAVIS ANOMALY PERSISTS: cycle=37843 + cycle=3087 in bot log tail — orphan/duplicate bot process. Bot-internal Mavis cycle=3087 at 12:50:19 EXECUTE_PLAN NIFTY conf=0.85 — same as 12:45 — blocked by HTTP 400. BANKNIFTY BLOCK at 12:50:19. Bias UNCHANGED cautious. Decision: HOLD. After HTTP 400 fix (chunk symbols into <=50 batches) + bot restart, cron can re-issue Plan A NIFTY iron_condor — IF both buffers still > triggers. Time-budget concern (CRITICAL): 40 min to 13:30 cutoff. If fix not in by ~13:00 (10 min from now), the entire paper session is wasted. Beyond 13:30 the bot's no-new-entries rule kicks in."
    },
    "tick_context": {
        "previous_decision_ist": "2026-08-31 12:45:00",
        "previous_decision_bias": "cautious",
        "previous_decision_actions_count": 0,
        "decision_changed": False,
        "decision_change_reason": "12:50 IST cron tick (5 min after 12:45, 200 min into regular session). Structural decision (HOLD, 0 actions, bias cautious) UNCHANGED from 12:45 + 12:40 + 12:35. (a) NO ESCALATION this tick — 12:15 escalation already surfaced the P1 to user. (b) 11th CONSECUTIVE TICK of structural HTTP 400 blocker. 60 min of blocked execution. (c) Spot 12:45->12:50: NIFTY +3.80pt GREEN bounce, BNF -13.60pt RED continuation. Plan A buffers DIVERGED: NIFTY improved to +50.65pt (back >50pt), BNF reduced to +33.85pt (second tick <50pt — approaching 57300 trigger). (d) DUAL MAVIS ANOMALY PERSISTS: cycle=37843 + cycle=3087 in bot log (12:50:15 and 12:50:19) — orphan bot process pattern from AGENTS.md. (e) Telegram will dedupe (bias same, actions same, note same shape with '11th' replacing '10th') — this is correct because the user has already been alerted and the situation is structurally unchanged. (f) Bot-internal Mavis cycle=3087 at 12:50:19 EXECUTE_PLAN NIFTY iron_condor conf=0.85 — same as 12:45 — blocked by HTTP 400. (g) 0 open positions. (h) User-actionable paths unchanged. (i) Time-budget (CRITICAL): 40 min to 13:30 cutoff, 1h40m to 14:30 force-square-off, 2h40m to 15:30 close. If fix not in by ~13:00 (10 min from now) the entire paper session is wasted.",
        "monday_brief_summary": {
            "regime_hint": "risk_on",
            "india_open_gap_signal": "gap_up",
            "recommended_posture": "normal",
            "max_risk_per_trade_pct": 2.0,
            "skip_first_30min_per_brief": False,
            "skip_first_30min_per_brief_rationale": "gap_up -> skip 30min (brief internal contradiction: explicit flag=false but rationale recommends skip)",
            "preferred_strategies": [
                "bull_call_vertical",
                "iron_condor"
            ],
            "key_catalysts": [
                "S&P +0.74pct Friday - US tailwind for Monday Asia open",
                "Nasdaq +1.57pct Friday - tech rally spillover",
                "India VIX 11.1 - calm, premium-selling favorable"
            ],
            "key_risks": [
                "Bullion/geopolitics (US jobs data, Iran tensions)",
                "Mcap drop of 7 top firms (Bharti Airtel, RIL)"
            ],
            "next_session_open_ist": "2026-08-31T09:15:00",
            "brief_as_of": "2026-08-30T21:01:10+05:30"
        },
        "log_tail_evidence_bot_alive_but_path_broken_http400_dual_mavis": "12:50:15.953 INFO SCAN cycle=37843 BANKNIFTY spot=57343.40 atm=57300 opts=18 regime=range conf=0.40 adx=0.2 mom=+0.00 | 12:50:15.954 MAVIS cycle=37843 BANKNIFTY | Mavis plan is for NIFTY, not BANKNIFTY \u2014 falling through to template | 12:50:16.222 WARNING _fetch_option_quotes:560 HTTP 400 | 12:50:18.477 WARNING _fetch_option_quotes:560 HTTP 400 | 12:50:18.803 LiveKotak heartbeat: authed=True subscribed=48 latest=48 tick_count=142970 | 12:50:19.554 SCAN cycle=3087 NIFTY spot=24070.65 atm=24050 opts=18 regime=range conf=0.40 adx=0.2 mom=+0.00 | 12:50:19.555 MAVIS cycle=3087 NIFTY | EXECUTE_PLAN: iron_condor confidence=0.85 reason=mavis_override: NIFTY spot 24090.85 inside expected range [23922.84, 24258.86] (thesis expected_move 168pt). Sell wings | 12:50:19.583 SCAN cycle=3087 BANKNIFTY spot=57333.85 atm=57300 opts=18 regime=range conf=0.40 adx=0.5 mom=-0.00 | 12:50:19.584 MAVIS cycle=3087 BANKNIFTY | BLOCK: Mavis plan is for NIFTY, not BANKNIFTY | 12:50:20.760 WARNING _fetch_option_quotes:560 HTTP 400 | 12:50:23.102 WARNING _fetch_option_quotes:560 HTTP 400 | 12:50:25.390 WARNING _fetch_option_quotes:560 HTTP 400 | 12:50:27.611 WARNING _fetch_option_quotes:560 HTTP 400 | 12:50:30.849 WARNING _fetch_option_quotes:560 HTTP 400 | 12:50:33.076 WARNING _fetch_option_quotes:560 HTTP 400"
    },
    "actions_count": 0,
    "timestamp": "2026-08-31T07:20:00Z"
}

# Update top-level fields
data["call_count_today"] = 68
data["timestamp"] = "2026-08-31T07:20:00Z"

# Update last_decision
data["last_decision"] = new_decision

# Write back
p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
print("brain_state.json updated for 12:50 IST cron tick")
print(f"call_count_today: {data['call_count_today']}")
print(f"timestamp: {data['timestamp']}")
print(f"last_decision.ist_time: {data['last_decision']['ist_time']}")
print(f"last_decision.bias: {data['last_decision']['bias']}")
print(f"last_decision.actions_count: {data['last_decision']['actions_count']}")
print(f"last_decision.note: {data['last_decision']['note']}")
