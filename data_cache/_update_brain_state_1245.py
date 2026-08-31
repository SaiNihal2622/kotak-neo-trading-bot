#!/usr/bin/env python3
"""Update brain_state.json with the 12:45 IST trader-desk decision.

Replaces last_decision with a new object, increments call_count_today,
and updates the top-level timestamp. Keeps history intact.
"""
import json
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

STATE_PATH = Path("C:/Users/saini/.minimax-agent/projects/kotak-neo-bot/data_cache/brain_state.json")

IST = timezone(timedelta(hours=5, minutes=30))
NOW_IST = datetime(2026, 8, 31, 12, 45, 0, tzinfo=IST)
NOW_UTC = NOW_IST.astimezone(timezone.utc)

new_decision = {
    "ts": NOW_UTC.strftime("%Y-%m-%dT%H:%M:%SZ"),
    "ist_time": NOW_IST.strftime("%Y-%m-%d %H:%M:%S"),
    "bias": "cautious",
    "source": "mavis",
    "max_positions": 0,
    "actions": [],
    "note": "p1_blocker_http400_batch_size_10th_consecutive_tick_dual_mavis_cycle_anomaly_37783_plus_3027",
    "decision_summary": (
        "12:45 IST cron tick (5 min after 12:40, 195 min into regular session, market_session=regular). "
        "HOLD, 0 actions, bias UNCHANGED at cautious. (a) ROOT CAUSE UNCHANGED: HTTP 400 'Please set the Neo "
        "symbol max value to 50' still firing every 2-3 sec on kotak_bot/data/kotak_prod_feed.py:"
        "_fetch_option_quotes:560 (bot log tail 12:45:15 to 12:45:29 = 6 warnings in 14s window). "
        "10th CONSECUTIVE TICK of structural blocker (11:50, 12:00, 12:10, 12:15, 12:20, 12:25, 12:30, 12:35, "
        "12:40, 12:45). 55 min of blocked execution since first identification at 11:50. "
        "(b) NEW ANOMALY DETECTED: dual Mavis cycle counters in 12:45 log tail — cycle=37783 (older/orphan "
        "Mavis process, much higher counter) AND cycle=3027 (current bot Mavis, +60 from 12:40's 2967, "
        "consistent with 5-min delta). This is the orphan-bot-process pattern documented in AGENTS.md. "
        "Two Mavis instances appear to be writing to bot_stderr.log in interleaved fashion. "
        "(c) Live spot evolution 12:40 -> 12:45: NIFTY 24073.15 -> 24066.85 -6.30pt (RED pullback); "
        "BNF 57374.95 -> 57347.45 -27.50pt (RED pullback, just barely above 57350). "
        "(d) Plan A iron_condor still 2/2 underlying TRIGGERED: NIFTY 24066.85 GT 24020 +46.85pt above "
        "(buffer REDUCED from +53.15pt at 12:40 by -6.30pt but still healthy), BNF 57347.45 GT 57300 "
        "+47.45pt above (buffer REDUCED from +74.95pt at 12:40 by -27.50pt, now <50pt for first time — "
        "approaching trigger but still well above). (e) Bot-internal Mavis cycle=3027 (and 37783) still "
        "firing EXECUTE_PLAN NIFTY iron_condor conf=0.85 — same as 12:40. Blocked by same HTTP 400. "
        "(f) VIX 11.165 (calm, 1.0x mult). Macro quiet, in_blackout=false, upcoming=[]. "
        "(g) 5d candle regime: NIFTY range conf 0.7, BNF range conf 0.7 — INTACT. "
        "(h) Research PDF still failing — candle+macro+VIX-only mode. "
        "(i) 0 open positions. Capital Rs.1,09,978, realized +Rs.9,978. "
        "(j) Bias UNCHANGED cautious — 12:15 escalation already surfaced P1. Re-escalating would be "
        "misleading. (k) Decision structurally identical to 12:40 + 12:35. (l) TIME-BUDGET (CRITICAL): "
        "45 min to 13:30 cutoff, 1h45m to 14:30 force-square-off, 2h30m to 15:15 square-off. "
        "The fix is needed in by ~13:00 (15 min from now) to save the paper session. "
        "Beyond 13:30 the cron cannot enter new positions even with the fix."
    ),
    "rationale": (
        "12:45 IST cron tick (5 min after 12:40, market_session=regular, 195 min into regular session). "
        "HOLD, 0 actions, bias UNCHANGED cautious. (a) Structural blocker UNCHANGED: HTTP 400 'Please set "
        "the Neo symbol max value to 50' still firing every 2-3 sec on kotak_bot/data/kotak_prod_feed.py:"
        "_fetch_option_quotes:560. 6 warnings in the 14s window 12:45:15 to 12:45:29 in the bot log "
        "tail. The execution path for any new options order (iron condor pricing, Mavis EXECUTE_PLAN, "
        "post-decision quote fetch) is BLOCKED. (b) 10th CONSECUTIVE TICK of the same structural blocker "
        "(11:50, 12:00, 12:10, 12:15, 12:20, 12:25, 12:30, 12:35, 12:40, 12:45). 55 min of blocked "
        "execution. (c) NEW ANOMALY this tick: dual Mavis cycle counters in bot log — cycle=37783 AND "
        "cycle=3027 within the same minute (12:45:14 vs 12:45:18). The 3027 counter is consistent with "
        "the 12:40 cycle=2967 (+60 in 5 min ≈ 1 cycle per 5 sec). The 37783 counter is anomalous — "
        "either an orphan Mavis process still running with the old code, or a new Mavis that was "
        "instantiated with a different counter baseline. This matches the AGENTS.md 'Orphan bot "
        "processes' known-issue. The 12:40 log did NOT show this dual cycle, so the divergence started "
        "between 12:40 and 12:45. (d) Live spot evolution 12:40 -> 12:45: NIFTY -6.30pt, BNF -27.50pt "
        "RED. Plan A iron_condor still 2/2 underlying TRIGGERED but BOTH buffers REDUCED from 12:40. "
        "NIFTY 24066.85 GT 24020 +46.85pt, BNF 57347.45 GT 57300 +47.45pt. BNF buffer now <50pt for "
        "first time — approaching trigger but still well above. (e) Plan B bear_put_vertical still 0/2 "
        "(NIFTY 24066.85 NOT < 24000, BNF 57347.45 NOT < 57250). Plan C short_strangle NOT triggered "
        "(VIX 11.165 not > 12). (f) Bot-internal Mavis cycle=3027 EXECUTE_PLAN NIFTY iron_condor "
        "conf=0.85 (NIFTY spot 24090.85 inside expected range [23922.84, 24258.86], thesis expected_move "
        "168pt) — same as 12:40 — blocked by HTTP 400. The second Mavis at cycle=37783 is also firing "
        "EXECUTE_PLAN. Both blocked. (g) VIX 11.165 calm 1.0x mult, no IV expansion. Macro quiet, "
        "in_blackout=false, upcoming=[]. (h) Candle regime: NIFTY range conf 0.7 (range_pct 0.56%), "
        "BNF range conf 0.7 (range_pct 0.68%). 5d trend NIFTY -0.63% DOWN, BNF -0.32% FLAT (slightly "
        "DEEPER from -0.26% at 12:40). Thesis INTACT. (i) Research unavailable. (j) 0 open positions, "
        "capital Rs.1,09,978, realized +Rs.9,978. (k) NOT re-issuing iron_condor action because: (i) the "
        "order path is structurally blocked by HTTP 400, (ii) re-issuing would create an 11th consumed "
        "action with no fill, (iii) the fix is a CODE CHANGE + bot restart, not a cron decision, "
        "(iv) buffers are REDUCING but still above trigger. (l) Bias UNCHANGED cautious. (m) "
        "USER-ACTIONABLE PATHS UNCHANGED + 1 new: (i) HTTP 400 fix = chunk symbols into <=50 batches "
        "in kotak_bot/data/kotak_prod_feed.py::_fetch_option_quotes around line 560, (ii) nssm restart "
        "KotakBotPaper to pick up new code, (iii) orphan bot process needs admin UAC for taskkill /F /T "
        "/PID, (iv) NEW: investigate the dual Mavis cycle anomaly (37783 + 3027) — likely two bot "
        "processes are running concurrently. (n) Time-budget (CRITICAL): 45 min to 13:30 cutoff, "
        "1h45m to 14:30 force-square-off, 2h30m to 15:15 square-off. The fix is needed in by ~13:00 "
        "(15 min from now) to save the paper session. Beyond 13:30, even with the fix, the cron cannot "
        "enter new positions. (o) Actions 0 -> 0 (HOLD). Decision structurally identical to 12:40 + 12:35."
    ),
    "risk_budget_reasoning": (
        "Risk budget = 0pct new capital at 12:45 IST. (a) No new actions this tick (HOLD). (b) Bottleneck "
        "is HTTP 400 batch size in kotak_prod_feed._fetch_option_quotes, not thesis quality. (c) Thesis "
        "remains EXCELLENT in isolation: range regime both conf 0.7, VIX 11.165 calm 1.0x mult, macro "
        "quiet, monday brief risk_on preferred iron_condor, Mavis expected range [23922.84, 24258.86] "
        "still contains NIFTY 24066.85 (inside lower band by ~144pt, comfortable), BNF 57347.45 above "
        "57300 trigger by +47.45pt (REDUCED from +74.95pt at 12:40, but still above trigger). "
        "(d) Plan A iron_condor still 2/2 underlying TRIGGERED (NIFTY 24066.85 GT 24020 +46.85pt, "
        "BNF 57347.45 GT 57300 +47.45pt) — BOTH buffers REDUCED from 12:40 but still above trigger. "
        "BNF now <50pt buffer — first tick this tight, monitor closely. Plan B 0/2, Plan C 0/2. "
        "(e) 0pct risk budget because the order path is structurally blocked by HTTP 400. (f) Once the "
        "HTTP 400 fix ships and a bot restart picks it up, the cron can re-issue Plan A NIFTY iron "
        "condor at the next tick — IF both NIFTY and BNF buffers are still > their respective triggers. "
        "(g) Bias cautious does NOT increase risk_budget_pct (still 0pct) — it only changes the BIAS "
        "label. (h) Time-budget (CRITICAL): 45 min to 13:30 cutoff, 1h45m to 14:30 force-square-off, "
        "2h30m to 15:15 square-off. The fix is needed in by ~13:00 (15 min from now) to save the paper "
        "session. The 13:30 cutoff is a HARD limit: the cron will HOLD on all subsequent ticks even if "
        "the HTTP 400 is fixed, because the bot's no-new-entries rule kicks in."
    ),
    "candle_regime_evidence": {
        "NIFTY": {
            "confidence": 0.7,
            "regime": "range",
            "reason": "range=0.56pct tight (5d per fresh yfinance) + vix=11.165 calm band 1.0x mult. Live intraday at 12:45: NIFTY 24066.85 (RED -6.30pt from 24073.15 at 12:40). NIFTY vs brief close 24090.85 = -24.00pt gap down (slightly WIDENED from -17.70pt at 12:40 by -6.30pt). NIFTY vs 09:30 24040 = +26.85pt. NIFTY vs 24000 round support = +66.85pt ABOVE. NIFTY vs 24020 Plan A trigger = +46.85pt ABOVE TRIGGERED, buffer REDUCED from +53.15pt at 12:40 by -6.30pt. 5d candles (trader_state yfinance last 5d, refreshed 12:45): 24219.05, 24334.55, 24207.75, 24090.85, 24066.20. Today intraday bar 2026-08-31: open 24117.55 high 24128.70 low 23993.60 close 24066.20. adx low. Range-bound, low-vol, supportive of iron condor. Thesis intact but execution path blocked by HTTP 400 batch size (10th consecutive tick of blocker, 55 min blocked).",
            "range_pct": 0.56,
            "last_close": 24066.2,
            "trend_5d": "down",
            "change_5d_pct": -0.63
        },
        "BANKNIFTY": {
            "confidence": 0.7,
            "regime": "range",
            "reason": "range=0.68pct tight (5d per fresh yfinance) + vix=11.165 calm band 1.0x mult. Live intraday at 12:45: BNF 57347.45 (RED -27.50pt from 57374.95 at 12:40, dropped below 57350). BNF vs brief close 57509.95 = -162.50pt gap down (WIDENED from -135.00pt at 12:40 by -27.50pt). BNF vs 57300 = +47.45pt ABOVE — approaching trigger, <50pt buffer for first time. 5d candles: 57525.95, 57514.20, 57783.75, 57509.95, 57341.65. Today intraday bar: open 57353.75 high 57576.25 low 57187.35 close 57341.65. Range-bound. Mavis plan is for NIFTY only, not BANKNIFTY — defer.",
            "range_pct": 0.68,
            "last_close": 57341.65,
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
        "fallback": "Research PDF download still failing (kotak_research.download_latest_research_pdf:52 WARNING at 12:46:15). Candle+macro+VIX-only mode. No max_pain, PCR, or FII flows available. Defer to: (a) candle_regime both range conf 0.7, (b) VIX 11.165 calm 1.0x mult, (c) US S&P +0.74pct / Nasdaq +1.57pct Fri — monday_brief catalyst (5d), (d) preferred_strategies from brief = [bull_call_vertical, iron_condor] — iron condor is the preferred structure for range regime, (e) Mavis thesis engine INDEPENDENTLY fired EXECUTE_PLAN for NIFTY iron_condor at confidence 0.85 with thesis expected_move 168pt, range [23922.84, 24258.86], NIFTY spot 24090.85 inside range. No research-driven bias override needed. The decision to HOLD is based on the order placement path being broken, not on research-driven bias."
    },
    "open_positions_summary": {
        "count": 0,
        "max_positions_limit": 2,
        "post_trade_count": 0,
        "max_reached": False,
        "details": [],
        "note": "0 -> 0 open positions this tick (HOLD, no actions). Capital 1,09,978 INR, realized +9,978 INR. Spot evolution 12:40 -> 12:45: NIFTY -6.30pt (24066.85 vs 24073.15 at 12:40), BNF -27.50pt (57347.45 vs 57374.95 at 12:40). BOTH buffers REDUCED from 12:40: NIFTY buffer +46.85pt (was +53.15pt), BNF buffer +47.45pt (was +74.95pt, now <50pt for first time — approaching 57300 trigger). Plan A iron_condor still 2/2 underlying TRIGGERED. ROOT CAUSE UNCHANGED: HTTP 400 still firing every 2-3 sec on _fetch_option_quotes. 10th CONSECUTIVE TICK of structural blocker. 55 min of blocked execution. NEW ANOMALY: dual Mavis cycle counters (37783 + 3027) in bot log tail — suggests orphan/duplicate bot process. Bot-internal Mavis cycle=3027 at 12:45:18 EXECUTE_PLAN NIFTY conf=0.85 — same as 12:40 — blocked by HTTP 400. BANKNIFTY BLOCK at 12:45:18. Bias UNCHANGED cautious. Decision: HOLD. After HTTP 400 fix (chunk symbols into <=50 batches) + bot restart, cron can re-issue Plan A NIFTY iron_condor — IF both buffers still > triggers. Time-budget concern (CRITICAL): 45 min to 13:30 cutoff. If fix not in by ~13:00 (15 min from now), the entire paper session is wasted. Beyond 13:30 the bot's no-new-entries rule kicks in."
    },
    "tick_context": {
        "previous_decision_ist": "2026-08-31 12:40:00",
        "previous_decision_bias": "cautious",
        "previous_decision_actions_count": 0,
        "decision_changed": False,
        "decision_change_reason": "12:45 IST cron tick (5 min after 12:40, 195 min into regular session). Structural decision (HOLD, 0 actions, bias cautious) UNCHANGED from 12:40 + 12:35. (a) NO ESCALATION this tick — 12:15 escalation already surfaced the P1 to user. (b) 10th CONSECUTIVE TICK of structural HTTP 400 blocker. 55 min of blocked execution. (c) Spot 12:40->12:45: BOTH NIFTY (-6.30pt) and BNF (-27.50pt) RED pulled back. Plan A buffers BOTH REDUCED, BNF now <50pt buffer for first time. (d) NEW ANOMALY: dual Mavis cycle counters in bot log (cycle=37783 AND cycle=3027 within 12:45) — orphan bot process pattern from AGENTS.md. (e) Telegram will dedupe (bias same, actions same, note same shape with '10th' replacing '9th') — this is correct because the user has already been alerted and the situation is structurally unchanged. (f) Bot-internal Mavis cycle=3027 at 12:45:18 EXECUTE_PLAN NIFTY iron_condor conf=0.85 — same as 12:40 — blocked by HTTP 400. (g) 0 open positions. (h) User-actionable paths unchanged + 1 new: investigate dual Mavis anomaly. (i) Time-budget (CRITICAL): 45 min to 13:30 cutoff, 1h45m to 14:30 force-square-off, 2h30m to 15:15 square-off. If fix not in by ~13:00 (15 min from now) the entire paper session is wasted.",
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
                "India VIX 11.1 - calm, premium-selling favorable"
            ],
            "key_risks": [
                "Bullion/geopolitics (US jobs data, Iran tensions)",
                "Mcap drop of 7 top firms (Bharti Airtel, RIL)"
            ],
            "next_session_open_ist": "2026-08-31T09:15:00",
            "brief_as_of": "2026-08-30T21:01:10+05:30"
        },
        "log_tail_evidence_bot_alive_but_path_broken_http400_dual_mavis": "12:45:14.311 INFO MAVIS cycle=37783 NIFTY | EXECUTE_PLAN: iron_condor confidence=0.85 reason=mavis_override: NIFTY spot 24090.85 inside expected range [23922.84, 24258.86] (thesis expected_move 168pt). Sell wings | 12:45:14.428 SCAN cycle=37783 BANKNIFTY spot=57347.45 atm=57300 opts=18 regime=range conf=0.40 adx=1.8 mom=-0.00 | 12:45:14.429 MAVIS cycle=37783 BANKNIFTY | Mavis plan is for NIFTY, not BANKNIFTY — falling through to template | 12:45:15.620 WARNING _fetch_option_quotes:560 HTTP 400 | 12:45:17.865 WARNING _fetch_option_quotes:560 HTTP 400 | 12:45:18.168 SCAN cycle=3027 NIFTY spot=24066.85 atm=24050 opts=18 regime=range conf=0.40 adx=1.4 mom=-0.00 | 12:45:18.170 MAVIS cycle=3027 NIFTY | EXECUTE_PLAN: iron_condor confidence=0.85 reason=mavis_override: NIFTY spot 24090.85 inside expected range [23922.84, 24258.86] (thesis expected_move 168pt). Sell wings | 12:45:18.240 SCAN cycle=3027 BANKNIFTY spot=57351.25 atm=57400 opts=18 regime=range conf=0.40 adx=2.7 mom=-0.00 | 12:45:18.242 MAVIS cycle=3027 BANKNIFTY | BLOCK: Mavis plan is for NIFTY, not BANKNIFTY | 12:45:18.744 LiveKotak heartbeat: authed=True subscribed=48 latest=48 tick_count=139274 | 12:45:20.162 WARNING _fetch_option_quotes:560 HTTP 400 | 12:45:22.417 WARNING _fetch_option_quotes:560 HTTP 400 | 12:45:24.635 WARNING _fetch_option_quotes:560 HTTP 400 | 12:45:26.951 WARNING _fetch_option_quotes:560 HTTP 400 | 12:45:29.180 WARNING _fetch_option_quotes:560 HTTP 400"
    },
    "actions_count": 0,
    "timestamp": NOW_UTC.strftime("%Y-%m-%dT%H:%M:%SZ")
}

# Load current state
with open(STATE_PATH, "r", encoding="utf-8") as f:
    state = json.load(f)

# Increment call_count_today
state["call_count_today"] = state.get("call_count_today", 0) + 1

# Update top-level timestamp
state["timestamp"] = NOW_UTC.strftime("%Y-%m-%dT%H:%M:%SZ")

# Replace last_decision
state["last_decision"] = new_decision

# Write back with indent=2 to match existing style
with open(STATE_PATH, "w", encoding="utf-8") as f:
    json.dump(state, f, indent=2, ensure_ascii=False)

print(f"OK: brain_state.json updated. call_count_today={state['call_count_today']}, timestamp={state['timestamp']}")
print(f"last_decision.ist_time={new_decision['ist_time']}, bias={new_decision['bias']}, actions={len(new_decision['actions'])}")
print(f"note={new_decision['note']}")
