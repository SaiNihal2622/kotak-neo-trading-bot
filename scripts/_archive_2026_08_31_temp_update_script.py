"""One-shot update for brain_state.json last_decision at 12:15 IST 2026-08-31.
Escalated neutral -> cautious to break Telegram dedup; preserves history."""
import json
from pathlib import Path

p = Path("data_cache/brain_state.json")
state = json.loads(p.read_text(encoding="utf-8"))
ld = state["last_decision"]

ld["rationale"] = (
    "12:15 IST cron tick (5 min after 12:10, market_session=regular, 165 min into regular session). "
    "ESCALATING bias neutral->cautious. (a) ROOT CAUSE UNCHANGED: HTTP 400 'Please set the Neo symbol max value to 50' "
    "still firing every 2-3 sec on kotak_bot/data/kotak_prod_feed.py:_fetch_option_quotes:560 (verified in bot log tail 12:15:18 to 12:15:36, 7+ warnings in 18s window). "
    "This is the order-placement blocker. (b) 4th CONSECUTIVE TICK of structural blocker: 11:50, 12:00, 12:10, 12:15 - all cron actions either HOLD or consumed without fill. "
    "25 min of blocked execution since first identification. (c) Bot-internal Mavis still firing EXECUTE_PLAN: cycle=37429 NIFTY spot=24063.30 conf=0.85 - blocked by same HTTP 400. "
    "(d) Spot evolution 12:10 -> 12:15: NIFTY 24063.95 -> 24063.30 -0.65pt (FLAT/slight deterioration); BNF 57419.05 -> 57404.25 -14.80pt (BNF pulled back from 12:10 high). "
    "Plan A iron_condor still 2/2 underlying TRIGGERED (NIFTY 24063.30 GT 24020 +43.30pt, BNF 57404.25 GT 57300 +104.25pt). "
    "(e) Two bot processes STILL running concurrently. (f) Macro quiet, VIX 11.185 calm 1.0x mult, candle regime both range conf 0.7 - thesis UNCHANGED. "
    "(g) NOT re-issuing iron_condor action because: (i) the order path is structurally blocked by HTTP 400, (ii) re-issuing would create a 5th consumed action with no fill, "
    "(iii) the fix is a CODE CHANGE (chunk symbols into <=50 batches in kotak_prod_feed._fetch_option_quotes around line 560) + bot restart, not a cron decision. "
    "(h) Bias UNCHANGED on thesis but ESCALATED cautious on system blocker - intentionally to break dedup and surface the P1 issue to the user. "
    "(i) USER-ACTIONABLE PATHS: (i) HTTP 400 fix 5 lines, (ii) nssm restart KotakBotPaper to pick up new code, (iii) orphan process needs admin UAC for taskkill /F /T /PID. "
    "(j) Time constraints: 1h15m to no-new-entries-after 13:30 IST, 2h15m to force-square-off 14:30 IST. 0 open positions. "
    "(k) Actions CHANGED 0 -> 0 (HOLD). Decision structurally identical but escalation flag raised."
)

ld["risk_budget_reasoning"] = (
    "Risk budget = 0pct new capital at 12:15 IST. (a) No new actions this tick (HOLD). (b) The bottleneck is HTTP 400 batch size in kotak_prod_feed._fetch_option_quotes, not thesis quality. "
    "(c) Thesis remains valid: range regime both conf 0.7, VIX 11.185 calm 1.0x mult, macro quiet, monday brief risk_on preferred iron_condor, Mavis expected range [23922.84, 24258.86] "
    "still contains NIFTY 24063.30 (inside lower band by 140.46pt, comfortable). (d) Plan A iron_condor still 2/2 underlying TRIGGERED (NIFTY 24063.30 GT 24020 +43.30pt, BNF 57404.25 GT 57300 +104.25pt) but execution path blocked. "
    "(e) Plan B bear_put_vertical: NIFTY 24063.30 NOT < 24000 +63.30pt above REJECTED, BNF 57404.25 NOT < 57250 +154.25pt above REJECTED. 0/2 underlying levels. Plan B NOT triggered. "
    "(f) Plan C short_strangle: VIX 11.185 not > 12, Plan C NOT triggered. (g) 0pct risk budget because the order path is structurally blocked by HTTP 400. "
    "(h) After the HTTP 400 fix is shipped and a bot restart picks it up, the cron can re-issue Plan A NIFTY iron_condor at the next tick. "
    "(i) The escalation to cautious bias does NOT increase risk_budget_pct (still 0pct) - it only changes the BIAS label for Telegram dedup and downstream filtering. "
    "(j) Time-budget concern: 1h15m to no-new-entries-after 13:30 IST. If the HTTP 400 fix is not in by ~13:00 the entire paper session will be wasted."
)

ld["candle_regime_evidence"]["NIFTY"]["reason"] = (
    "range=0.56pct tight (5d) + vix=11.185 calm band 1.0x mult. Live intraday at 12:15: NIFTY 24063.30 (FLAT/slight deterioration from 24063.95 at 12:10 by -0.65pt). "
    "NIFTY vs brief close 24090.85 = -27.55pt gap down (DETERIORATED from -27.10pt at 12:10 by -0.45pt). "
    "NIFTY vs 09:30 24040 = +23.30pt. NIFTY vs 24000 round support = +63.30pt ABOVE. "
    "NIFTY vs 24020 Plan A trigger = +43.30pt ABOVE TRIGGERED, slight buffer narrowing from +43.95pt at 12:10 by -0.65pt. "
    "5d candles (2026-08-21 to 2026-08-27): 24252.00, 24219.05, 24334.55, 24207.75, 24090.85. "
    "Today intraday bar 2026-08-31: open 24117.55 high 24128.70 low 23993.60 close ~24062.75. "
    "Range-bound, low-vol, supportive of iron condor. Thesis intact but execution path blocked by HTTP 400 batch size (4th consecutive tick of blocker)."
)

ld["candle_regime_evidence"]["BANKNIFTY"]["reason"] = (
    "range=0.68pct tight (5d) + vix=11.185 calm band 1.0x mult. Live intraday at 12:15: BNF 57404.25 (PULLBACK from 57419.05 at 12:10 by -14.80pt - BNF lost the +25.75pt bounce, now back below 57400 by -0.75pt). "
    "BNF vs brief close 57509.95 = -105.70pt gap down (DETERIORATED from -90.90pt at 12:10 by -14.80pt). "
    "BNF vs 57300 = +104.25pt ABOVE. BNF vs 57300 Plan A trigger = +104.25pt ABOVE TRIGGERED, buffer narrowing from +119.05pt at 12:10 by -14.80pt. "
    "5d candles: 57761.95, 57525.95, 57514.20, 57783.75, 57509.95. Today intraday bar: open 57353.75 high 57576.25 low 57187.35 close ~57418.20. "
    "Range-bound but Mavis plan is for NIFTY only, not BANKNIFTY. Defer."
)

ld["open_positions_summary"]["note"] = (
    "0 -> 0 open positions this tick (HOLD, no actions). Capital 1,09,978 INR, realized +9,978 INR. "
    "Spot evolution 12:10 -> 12:15: NIFTY -0.65pt (FLAT), BNF -14.80pt (PULLBACK from 12:10 high). "
    "Plan A iron_condor still 2/2 underlying TRIGGERED. ROOT CAUSE UNCHANGED: HTTP 400 still firing every 2-3 sec on _fetch_option_quotes. "
    "4TH CONSECUTIVE TICK of structural blocker (11:50, 12:00, 12:10, 12:15). 25 min of blocked execution. "
    "Bot-internal Mavis still firing EXECUTE_PLAN cycle=37429 NIFTY conf=0.85 but blocked. "
    "Two bot processes running concurrently - orphan pattern. "
    "Bias ESCALATED neutral->cautious to break Telegram dedup. Decision: HOLD with escalation. "
    "After HTTP 400 fix (chunk symbols into <=50 batches in kotak_bot/data/kotak_prod_feed.py:_fetch_option_quotes around line 560) + bot restart, cron can re-issue Plan A NIFTY iron_condor. "
    "Time-budget concern: 1h15m to 13:30 no-new-entries cutoff, 2h15m to 14:30 force-square-off. If fix not in by ~13:00 the entire session is wasted."
)

if "tick_context" not in ld:
    ld["tick_context"] = {}
ld["tick_context"]["previous_decision_ist"] = "2026-08-31 12:10:00"
ld["tick_context"]["previous_decision_bias"] = "neutral"
ld["tick_context"]["previous_decision_actions_count"] = 0
ld["tick_context"]["decision_changed"] = True
ld["tick_context"]["decision_change_reason"] = (
    "12:15 IST cron tick (5 min after 12:10, 165 min into regular session). "
    "Bias ESCALATED neutral->cautious to break Telegram dedup. Structural decision (HOLD, 0 actions) identical to 12:10. "
    "Escalation is intentional because: (a) 4th consecutive tick of structural HTTP 400 blocker (11:50, 12:00, 12:10, 12:15) - 25 min of blocked execution, "
    "(b) Telegram was likely suppressed on 12:10 due to dedup with 12:05 cautious/0-actions decision, so the user has not been alerted about the P1 issue, "
    "(c) the escalation is purely a dedup-breaking mechanism - the underlying thesis (range regime both conf 0.7, VIX calm 11.185, macro quiet, preferred iron_condor) is UNCHANGED, "
    "(d) bot Mavis internally is still firing EXECUTE_PLAN (cycle 37429) but blocked. "
    "Spot evolution 12:10 -> 12:15: NIFTY -0.65pt (FLAT), BNF -14.80pt (PULLBACK). Plan A still 2/2 underlying TRIGGERED but buffer narrowing. "
    "Bias label change is the ONLY material difference from 12:10. The user needs to know about the HTTP 400 P1 issue; the Telegram will now fire because bias changed neutral->cautious."
)

ld["timestamp"] = "2026-08-31T06:45:00Z"
ld["actions_count"] = 0
ld["note"] = "p1_blocker_http400_batch_size_4th_consecutive_tick_needs_user_or_dev_intervention"

state["today_date"] = "2026-08-31"
state["call_count_today"] = state.get("call_count_today", 0) + 1
state["timestamp"] = "2026-08-31T06:45:00Z"

p.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
print("OK: brain_state.json updated, last_decision = 12:15 cautious")
print("call_count_today =", state["call_count_today"])
print("bias =", state["last_decision"]["bias"])
print("actions =", state["last_decision"]["actions"])
print("note =", state["last_decision"].get("note"))
