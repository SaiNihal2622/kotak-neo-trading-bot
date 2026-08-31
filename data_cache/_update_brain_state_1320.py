#!/usr/bin/env python3
"""Update brain_state.json with new last_decision at 13:20 IST."""
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

PATH = Path(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json")

# 13:20 IST = 07:50 UTC
ist = datetime(2026, 8, 31, 13, 20, 0)
utc = ist - timedelta(hours=5, minutes=30)

# Load existing
data = json.loads(PATH.read_text(encoding="utf-8"))

# New last_decision
new_decision = {
    "ts": "2026-08-31T07:50:00Z",
    "ist_time": "2026-08-31 13:20:00",
    "bias": "cautious",
    "source": "mavis",
    "max_positions": 0,
    "actions": [],
    "note": "p1_blocker_http400_batch_size_17th_consecutive_tick_dual_mavis_3447_plus_38203_10min_to_cutoff_fix_window_even_more_closed",
    "decision_summary": "13:20 IST cron tick (5 min after 13:15, 230 min into regular session, market_session=regular). HOLD, 0 actions, bias UNCHANGED cautious. (a) ROOT CAUSE UNCHANGED: HTTP 400 \"Please set the Neo symbol max value to 50\" still firing every 2-3 sec on kotak_bot/data/kotak_prod_feed.py:_fetch_option_quotes:560 (fresh bot log tail 13:20:25 to 13:20:36 = 4 warnings in 11s window). 17th CONSECUTIVE TICK of structural blocker (11:50, 12:00, 12:10, 12:15, 12:20, 12:25, 12:30, 12:35, 12:40, 12:45, 12:50, 12:55, 13:00, 13:05, 13:10, 13:15, 13:20). 90 min of blocked execution since first identification at 11:50. (b) Live spot evolution 13:15 -> 13:20: NIFTY 24070.15 -> 24066.65 -3.50pt (slight RED, still holding above 24065); BNF 57404.10 -> 57391.70 -12.40pt (RED, back below 57400). (c) BUFFERS 13:15->13:20: NIFTY 24066.65 GT 24020 +46.65pt (DEEPER from +50.15pt at 13:15 by -3.50pt, still healthy >40pt), BNF 57391.70 GT 57300 +91.70pt (DEEPER from +104.10pt at 13:15 by -12.40pt, still well above trigger). Plan A iron_condor still 2/2 underlying TRIGGERED with healthy buffers. (d) FIX WINDOW EVEN MORE CLOSED: 10 min to 13:30 HARD limit (was 15 min at 13:15). Even if HTTP 400 fix is deployed RIGHT NOW, code+restart+first-scan path takes 3-5 min minimum, landing first fills at 13:25-13:30 which is borderline-over the cutoff. No realistic path to a filled entry before 13:30. (e) Plan B bear_put_vertical 0/2 (NIFTY 24066.65 NOT < 24000, BNF 57391.70 NOT < 57250). Plan C short_strangle NOT triggered (VIX 11.21 not > 12). (f) Bot-internal Mavis cycle=3447 at 13:20:27 EXECUTE_PLAN NIFTY iron_condor conf=0.85 - blocked by HTTP 400. DUAL MAVIS ANOMALY PERSISTS: cycle=3447 (current, +60 from 13:15 cycle=3387) AND cycle=38203 (orphan, +60 from 13:15 cycle=38143) within 1.5s. Both fire EXECUTE_PLAN. Orphan bot process pattern from AGENTS.md. (g) VIX 11.21 calm 1.0x mult. Macro quiet, in_blackout=false, upcoming=[]. (h) 5d candle regime UNCHANGED on 13:20 refresh: NIFTY range_pct 0.56% (5d), BNF range_pct 0.68% (5d). Range thesis still INTACT. (i) 0 open positions. Capital Rs.1,09,978, realized +Rs.9,978. (j) Bias UNCHANGED cautious - 12:15 escalation already surfaced P1 to user. (k) TIME-BUDGET (TERMINAL): 10 min to 13:30 cutoff (HARD limit), 1h10m to 14:30 force-square-off, 2h10m to 15:30 close. The HTTP 400 fix is no longer actionable for this session - even if deployed RIGHT NOW, it cannot result in a filled entry before 13:30. The fix is still valuable for FUTURE sessions (tomorrow onward).",
    "rationale": "13:20 IST cron tick (5 min after 13:15, market_session=regular, 230 min into regular session). HOLD, 0 actions, bias UNCHANGED cautious. (a) Structural blocker UNCHANGED: HTTP 400 \"Please set the Neo symbol max value to 50\" still firing every 2-3 sec on kotak_bot/data/kotak_prod_feed.py:_fetch_option_quotes:560. 4 warnings in the 11s window 13:20:25 to 13:20:36. Execution path for any new options order (iron condor pricing, Mavis EXECUTE_PLAN, post-decision quote fetch) is BLOCKED. (b) 17th CONSECUTIVE TICK of the same structural blocker. 90 min of blocked execution since 11:50 IST. (c) Live spot evolution 13:15 -> 13:20: NIFTY -3.50pt slight RED (24066.65 vs 24070.15 at 13:15, still holding above 24065), BNF -12.40pt RED (57391.70 vs 57404.10 at 13:15, back below 57400). Plan A iron_condor still 2/2 underlying TRIGGERED with healthy buffers: NIFTY 24066.65 GT 24020 +46.65pt (DEEPER from +50.15pt by -3.50pt, still >40pt), BNF 57391.70 GT 57300 +91.70pt (DEEPER from +104.10pt by -12.40pt, still well above trigger). (d) FIX WINDOW EVEN MORE CLOSED: 10 min to 13:30 HARD limit (was 15 min at 13:15). No realistic path to a filled entry before 13:30 even with immediate code+restart. Even the optimistic path (deploy NOW + 3min restart + first scan) lands first fills at ~13:25-13:30, borderline-over 13:30. The current paper session is effectively blocked. (e) Plan B bear_put_vertical still 0/2 (NIFTY 24066.65 NOT < 24000, BNF 57391.70 NOT < 57250). Plan C short_strangle NOT triggered (VIX 11.21 not > 12). (f) Bot-internal Mavis cycle=3447 EXECUTE_PLAN NIFTY iron_condor conf=0.85 (NIFTY spot 24090.85 inside expected range [23922.84, 24258.86], thesis expected_move 168pt) - same as 13:15/13:10/13:05/13:00 - blocked by HTTP 400. (g) DUAL MAVIS ANOMALY PERSISTS: cycle=3447 (current) + cycle=38203 (orphan) in bot log tail (13:20:27 and 13:20:26) - orphan bot process pattern from AGENTS.md. Tick count gap: current bot tick_count advancing (heartbeat at 13:20:33 shows tick_count=2038028) vs orphan at cycle=38203 (different heartbeat count). (h) VIX 11.21 calm 1.0x mult, no IV expansion. Macro quiet. (i) Candle regime 5d (per yfinance refresh at 13:20): NIFTY range_pct 0.56%, BNF range_pct 0.68% (UNCHANGED from 13:15). 5d trend NIFTY -0.63% (vs -0.66% at 13:15, slightly IMPROVED), BNF -0.23% (vs -0.44% at 13:15, IMPROVED). Both still classified range conf 0.7. Thesis INTACT. (j) Research unavailable. (k) 0 open positions, capital Rs.1,09,978, realized +Rs.9,978. (l) NOT re-issuing iron_condor action because: (i) the order path is structurally blocked by HTTP 400, (ii) the fix window has CLOSED (10 min to 13:30 HARD limit), (iii) re-issuing would just create another consumed action with no fill, (iv) the fix requires a code change + bot restart, NOT a cron decision. (m) Bias UNCHANGED cautious. (n) USER-ACTIONABLE PATHS UNCHANGED: (i) HTTP 400 fix = chunk symbols into <=50 batches in kotak_bot/data/kotak_prod_feed.py:_fetch_option_quotes around line 560, (ii) nssm restart KotakBotPaper to pick up new code, (iii) orphan bot process needs admin UAC for taskkill /F /T /PID, (iv) investigate the dual Mavis cycle anomaly (cycles 3447 + 38203). (o) Time-budget (TERMINAL): 10 min to 13:30 cutoff (HARD limit, no new entries after). Beyond 13:30, even with the fix, the cron cannot enter new positions. The current paper session is effectively blocked. (p) Actions 0 -> 0 (HOLD). Decision structurally identical to 13:15 + 13:10 + 13:05 + 13:00 + 12:55 + 12:50 + 12:45 + 12:40 + 12:35 + 12:30 + 12:25 + 12:20 + 12:15 + 12:10 + 12:00 + 11:50.",
    "risk_budget_reasoning": "Risk budget = 0pct new capital at 13:20 IST. (a) No new actions this tick (HOLD). (b) Bottleneck is HTTP 400 batch size in kotak_prod_feed._fetch_option_quotes, not thesis quality. (c) Thesis remains EXCELLENT and unchanged from 13:15: range regime both conf 0.7, range_pct 13:20 NIFTY 0.56% / BNF 0.68% (UNCHANGED from 13:15), VIX 11.21 calm 1.0x mult, macro quiet, monday brief risk_on preferred iron_condor, Mavis expected range [23922.84, 24258.86] still contains NIFTY 24090.85 (inside lower band by ~143pt, comfortable), BNF 57391.70 above 57300 trigger by +91.70pt (DEEPER from +104.10pt at 13:15 by -12.40pt, still well above trigger). (d) Plan A iron_condor still 2/2 underlying TRIGGERED with healthy buffers: NIFTY 24066.65 GT 24020 +46.65pt (DEEPER from +50.15pt by -3.50pt, still >40pt), BNF 57391.70 GT 57300 +91.70pt (DEEPER from +104.10pt by -12.40pt). Plan B 0/2, Plan C 0/2. (e) 0pct risk budget because: (i) the order path is structurally blocked by HTTP 400, (ii) the fix window has CLOSED - 10 min to 13:30 HARD limit (was 15 min at 13:15, now 10 min), (iii) no realistic path to a filled entry before 13:30. (f) Bias cautious does NOT increase risk_budget_pct (still 0pct) - it only changes the BIAS label. (g) Time-budget (TERMINAL): 10 min to 13:30 cutoff (HARD limit, no new entries after), 1h10m to 14:30 force-square-off, 2h10m to 15:30 close. The HTTP 400 fix is no longer actionable for this session - even if deployed RIGHT NOW, it cannot result in a filled entry before 13:30. The fix is still valuable for FUTURE sessions (tomorrow onward).",
    "candle_regime_evidence": {
        "NIFTY": {
            "confidence": 0.7,
            "regime": "range",
            "reason": "range=0.56pct tight (5d per fresh yfinance 13:20) + vix=11.21 calm band 1.0x mult. Live intraday at 13:20: NIFTY 24066.65 (RED -3.50pt from 24070.15 at 13:15, still holding above 24065). NIFTY vs brief close 24090.85 = -24.20pt gap down (slightly DEEPER from -20.70pt at 13:15 by -3.50pt). NIFTY vs 09:30 24040 = +26.65pt. NIFTY vs 24000 round support = +66.65pt ABOVE. NIFTY vs 24020 Plan A trigger = +46.65pt ABOVE TRIGGERED, buffer DEEPER from +50.15pt at 13:15 by -3.50pt (still >40pt, healthy). 5d candles (trader_state yfinance last 5d, refreshed 13:20): 24219.05, 24334.55, 24207.75, 24090.85, 24066.35. Today intraday bar 2026-08-31: open 24117.55 high 24128.70 low 23993.60 close 24066.35. adx low. Range-bound, low-vol, supportive of iron condor. Thesis intact. Execution path BLOCKED by HTTP 400 batch size (17th consecutive tick of blocker, 90 min blocked). Fix window EVEN MORE CLOSED at 10 min to 13:30 cutoff.",
            "range_pct": 0.56,
            "last_close": 24066.35,
            "trend_5d": "down",
            "change_5d_pct": -0.63
        },
        "BANKNIFTY": {
            "confidence": 0.7,
            "regime": "range",
            "reason": "range=0.68pct tight (5d per fresh yfinance 13:20) + vix=11.21 calm band 1.0x mult. Live intraday at 13:20: BNF 57391.70 (RED -12.40pt from 57404.10 at 13:15, back below 57400). BNF vs brief close 57509.95 = -118.25pt gap down (DEEPER from -105.85pt at 13:15 by -12.40pt). BNF vs 57300 = +91.70pt ABOVE. BNF vs 57300 Plan A trigger = +91.70pt ABOVE TRIGGERED, buffer DEEPER from +104.10pt at 13:15 by -12.40pt (still well above trigger). 5d candles: 57525.95, 57514.20, 57783.75, 57509.95, 57393.90. Today intraday bar: open 57353.75 high 57576.25 low 57187.35 close 57393.90. Range-bound. Mavis plan is for NIFTY only, not BANKNIFTY - defer.",
            "range_pct": 0.68,
            "last_close": 57393.90,
            "trend_5d": "flat",
            "change_5d_pct": -0.23
        }
    },
    "macro_evidence": {
        "upcoming": [],
        "in_blackout": False,
        "interpretation": "macro.upcoming is empty list, in_blackout=false, next_event_min=null. QUIET macro calendar. Monday brief macro_blackout_soon=false, macro_events_next_7d=[]. No RBI policy, Fed, or US CPI in immediate window. Macro layer is QUIET - no event-driven constraint on new entries today. The decision to HOLD is based on the order placement path being broken (HTTP 400 batch size) AND the fix window having CLOSED (10 min to 13:30 cutoff), NOT on macro concerns."
    },
    "research_evidence": {
        "available": False,
        "fallback": "Research PDF download still failing (kotak_research.download_latest_research_pdf:52 WARNING at 13:20). Candle+macro+VIX-only mode. No max_pain, PCR, or FII flows available. Defer to: (a) candle_regime both range conf 0.7, (b) VIX 11.21 calm 1.0x mult, (c) US S&P +0.74pct / Nasdaq +1.57pct Fri - monday_brief catalyst (5d), (d) preferred_strategies from brief = [bull_call_vertical, iron_condor] - iron condor is the preferred structure for range regime, (e) Mavis thesis engine INDEPENDENTLY fired EXECUTE_PLAN for NIFTY iron_condor at confidence 0.85 with thesis expected_move 168pt, range [23922.84, 24258.86], NIFTY spot 24090.85 inside range. No research-driven bias override needed. The decision to HOLD is based on the order placement path being broken AND the fix window having CLOSED, not on research-driven bias."
    },
    "open_positions_summary": {
        "count": 0,
        "max_positions_limit": 2,
        "post_trade_count": 0,
        "max_reached": False,
        "details": [],
        "note": "0 -> 0 open positions this tick (HOLD, no actions). Capital 1,09,978 INR, realized +9,978 INR. Spot evolution 13:15 -> 13:20: NIFTY -3.50pt slight RED (24066.65 vs 24070.15 at 13:15, still holding above 24065), BNF -12.40pt RED (57391.70 vs 57404.10 at 13:15, back below 57400). BUFFERS 13:15->13:20: NIFTY +46.65pt (was +50.15pt at 13:15, DEEPER by -3.50pt, still >40pt healthy), BNF +91.70pt (was +104.10pt at 13:15, DEEPER by -12.40pt, still well above trigger). Plan A iron_condor still 2/2 underlying TRIGGERED with healthy buffers. ROOT CAUSE UNCHANGED: HTTP 400 still firing every 2-3 sec on _fetch_option_quotes. 17th CONSECUTIVE TICK of structural blocker. 90 min of blocked execution. DUAL MAVIS ANOMALY PERSISTS: cycle=3447 + cycle=38203 in bot log tail (13:20:27 and 13:20:26) - orphan/duplicate bot process. Bot-internal Mavis cycle=3447 at 13:20:27 EXECUTE_PLAN NIFTY conf=0.85 - same as 13:15/13:10 - blocked by HTTP 400. BANKNIFTY BLOCK at 13:20:28. Bias UNCHANGED cautious. Decision: HOLD. FIX WINDOW EVEN MORE CLOSED: 10 min to 13:30 cutoff (HARD limit, was 15 min at 13:15). The HTTP 400 fix is no longer actionable for this session. The fix is still valuable for FUTURE sessions (tomorrow onward)."
    },
    "tick_context": {
        "previous_decision_ist": "2026-08-31 13:15:00",
        "previous_decision_bias": "cautious",
        "previous_decision_actions_count": 0,
        "decision_changed": False,
        "decision_change_reason": "13:20 IST cron tick (5 min after 13:15, 230 min into regular session). Structural decision (HOLD, 0 actions, bias cautious) UNCHANGED from 13:15 + 13:10 + 13:05 + 13:00 + 12:55 + 12:50 + 12:45 + 12:40 + 12:35 + 12:30 + 12:25 + 12:20 + 12:15 + 12:10 + 12:00 + 11:50. (a) NO ESCALATION this tick - 12:15 escalation already surfaced the P1 to user. (b) 17th CONSECUTIVE TICK of structural HTTP 400 blocker. 90 min of blocked execution. (c) BUFFER EVOLUTION 13:15->13:20: NIFTY +46.65pt (DEEPER from +50.15pt by -3.50pt, still >40pt healthy), BNF +91.70pt (DEEPER from +104.10pt by -12.40pt, still well above trigger). Buffers still HEALTHY but the path is still BLOCKED. (d) 5d trends 13:15->13:20: NIFTY -0.63% (was -0.66%, slightly IMPROVED), BNF -0.23% (was -0.44%, IMPROVED). Trend 5d is slightly IMPROVED. (e) range_pct 13:20 refresh: NIFTY 0.56% (5d), BNF 0.68% (5d) - per fresh yfinance. UNCHANGED from 13:15. (f) FIX WINDOW EVEN MORE CLOSED: 10 min to 13:30 cutoff (HARD limit, was 15 min at 13:15, no new entries after). Even immediate code+restart cannot deliver a filled entry before 13:30 (5-10 min from deploy to first fill = ~13:25-13:30, borderline-over 13:30). (g) DUAL MAVIS ANOMALY PERSISTS: cycle=3447 + cycle=38203 in bot log (13:20:27 and 13:20:26) - orphan bot process pattern from AGENTS.md. (h) Telegram will dedupe (bias same, actions same, note same shape with 17th replacing 16th) - this is correct because the user has already been alerted and the situation is structurally unchanged. (i) Bot-internal Mavis cycle=3447 at 13:20:27 EXECUTE_PLAN NIFTY iron_condor conf=0.85 - same as 13:15/13:10 - blocked by HTTP 400. (j) 0 open positions. (k) User-actionable paths unchanged from 13:15.",
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
        "log_tail_evidence_bot_alive_but_path_broken_http400_dual_mavis_fix_window_even_more_closed": "13:20:25.202 WARNING _fetch_option_quotes:560 HTTP 400 | 13:20:26.506 SCAN cycle=38203 NIFTY spot=24066.65 atm=24050 opts=18 regime=range conf=0.40 | 13:20:26.508 MAVIS cycle=38203 NIFTY EXECUTE_PLAN: iron_condor confidence=0.85 | 13:20:26.559 SCAN cycle=38203 BANKNIFTY spot=57391.70 | 13:20:26.560 MAVIS cycle=38203 BANKNIFTY Mavis plan is for NIFTY, not BANKNIFTY - falling through to template | 13:20:27.509 WARNING _fetch_option_quotes:560 HTTP 400 | 13:20:27.984 SCAN cycle=3447 NIFTY spot=24066.70 atm=24050 opts=18 regime=range conf=0.40 | 13:20:27.986 MAVIS cycle=3447 NIFTY EXECUTE_PLAN: iron_condor confidence=0.85 | 13:20:28.016 SCAN cycle=3447 BANKNIFTY spot=57392.65 | 13:20:28.017 MAVIS cycle=3447 BANKNIFTY BLOCK: Mavis plan is for NIFTY, not BANKNIFTY | 13:20:29.814 WARNING _fetch_option_quotes:560 HTTP 400 | 13:20:32.200 WARNING _fetch_option_quotes:560 HTTP 400 | 13:20:33.602 LiveKotak heartbeat: authed=True subscribed=54 latest=50 tick_count=2038028 | 13:20:34.424 WARNING _fetch_option_quotes:560 HTTP 400 | 13:20:36.705 WARNING _fetch_option_quotes:560 HTTP 400"
    },
    "actions_count": 0,
    "timestamp": "2026-08-31T07:50:00Z"
}

# Update last_decision
data["last_decision"] = new_decision

# Update top-level fields
data["timestamp"] = "2026-08-31T07:50:00Z"
data["call_count_today"] = data.get("call_count_today", 0) + 1

# Write back
PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"OK: brain_state.json updated. last_decision ist_time={new_decision['ist_time']}, bias={new_decision['bias']}, actions={new_decision['actions_count']}, call_count_today={data['call_count_today']}")
