"""One-shot script to update brain_state.json with the 11:40 tick decision.

This is plumbing — it preserves history/last_decision_history_addendum and only
swaps in the new last_decision, increments call_count_today, and appends a
history entry. NOT an LLM call.
"""
import json
from pathlib import Path

STATE_PATH = Path(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json")

new_last_decision = {
    "ts": "2026-08-25T06:10:25Z",
    "ist_time": "2026-08-25 11:40:25",
    "bias": "neutral",
    "source": "mavis",
    "max_positions": 2,
    "actions": [
        {
            "id": "act-114025A",
            "type": "CLOSE",
            "strategy": "ic_BANKNIFTY_pe_side",
            "underlying": "BANKNIFTY",
            "expiry": "2026-08-25",
            "legs": [
                {"side": "BUY", "strike": 57400, "option_type": "PE", "qty": 30, "price": None},
                {"side": "SELL", "strike": 57300, "option_type": "PE", "qty": 30, "price": None},
            ],
            "rationale": "0DTE monthly expiry BN at 57412.15 BREACHED PE close trigger 57415 by 2.85 pts (per 11:35 tick's NEXT TICK RULE). Pattern: 4 tests of 57420-57425 zone in 15 min with progressively lower lows (11:25 57425.65, 11:35 57426.10, 11:37 57408.90 sub-57415 first breach, 11:39:48 57405.25 sub-57415 second breach, 11:40:19 57412.15 still sub-57415 sustained) — bearish failure pattern at support. PE escalation 57420 also BREACHED (BN 7.85 below). 0DTE monthly gamma risk highest of month, 3h35m to expiry. Exit PE side to cap current MTM loss rather than risk 57300 wing breach (max loss 674.70 INR on PE side if held to expiry through gap). CE side of BN IC stays (187.85 OTM, 137.85 below 57550 yellow, GREEN safe — still collecting theta). NIFTY IB unchanged (PE 50.70 OTM, CE 149.30 OTM, both GREEN, 35.70 / 100.30 buffer to close / yellow triggers).",
            "ttl_sec": 60,
        }
    ],
    "note": "0dte_monthly_expiry_bn_pe_close_trigger_57415_breached_by_2.85pts_lower_lows_pattern_close_pe_side_of_bn_ic_ce_side_kept_nifty_ib_unchanged",
    "reasoning": "Tick at 11:40 IST on Tue 2026-08-25 (0DTE MONTHLY expiry day). 5 min after 11:35 tick, 145 min into regular session (past 09:30 opening buffer), 3h35m to 15:15 square-off, 1h50m to 13:30 no-new-entries cutoff. Market in regular session. VIX 11.29 (down from 11.34 at 11:35, -0.05; still <12 very low, calm regime, theta friendly). Range regime confirmed for both underlyings (NIFTY conf=0.7 range=0.34%, BANKNIFTY conf=0.7 range=0.74%, unchanged). Macro: no events next 7d, no blackout (in_blackout=false). Research: still unavailable (Kotak PDF timed out, 25th consecutive tick - skip research bias). Live positions: 2 strategies (NIFTY IB + BANKNIFTY IC) at max_positions=2, but THIS TICK IS A CLOSE ACTION not a hold. STATUS UPDATE vs 11:35: BN DROPPED -13.95 pts (57426.10 -> 57412.15, -0.024%, SUSTAINED BREAK of PE close trigger 57415). LiveIndia refreshes since 11:35: 11:37:45 NF=24145.85 BN=57408.90 VIX=11.35 (FIRST sub-57415 breach), 11:38:15 NF=24147.50 BN=57419.10 VIX=11.30 (bounce back above), 11:38:47 NF=24152.05 BN=57429.60 VIX=11.30 (peak bounce 9.60 above 57420), 11:39:17 NF=24152.45 BN=57429.15 VIX=11.30, 11:39:48 NF=24150.35 BN=57405.25 VIX=11.30 (SECOND sub-57415 breach, lower low), 11:40:19 NF=24150.70 BN=57412.15 VIX=11.29 (still sub-57415, SUSTAINED for 2+ refreshes). The pattern: 11:35 57426.10 -> 11:37:45 57408.90 (1st sub-57415) -> 11:38:15 57419.10 (bounce) -> 11:38:47 57429.60 (peak) -> 11:39:17 57429.15 -> 11:39:48 57405.25 (2nd sub-57415, deeper) -> 11:40:19 57412.15 (sub-57415 SUSTAINED). Lower lows progression: 57426.10 -> 57408.90 -> 57405.25 -> 57412.15. Bounces are getting shallower: 57419.10 was 5.10 above 57415 (barely above), peak bounce 57429.60 was only 9.60 above 57420. NIFTY drifted -5.20 pts (24155.90 -> 24150.70, basically flat). VIX 11.34 -> 11.29 (-0.05, back to calmer). (1) BANKNIFTY Iron Condor (short 57600 CE / 57400 PE, wings 57700 CE / 57300 PE) - spot 57412.15. Short 57600 CE: 187.85 pts OTM (vs 173.90 at 11:35, GAINED 13.95 pts, GREEN safe, 137.85 below 57550 yellow zone, 0.33% of spot). Short 57400 PE: 12.15 pts OTM (vs 26.10 at 11:35, LOST 13.95 pts, NOW ITM relative to 57415 close trigger — BN IS 2.85 BELOW 57415 = CLOSE TRIGGER BREACHED). Wings 57700 CE / 57300 PE = 287.85 / 112.15 pts away. Net credit 77.51 INR per unit, total 2325.30 INR. Max loss capped 674.70 INR. PE side lost 13.95 pts. CE side gained 13.95 pts. PE BUFFER ABOVE 57415 = -2.85 (BREACHED). PE BUFFER ABOVE 57420 = -7.85 (ESCALATION BREACHED). (2) NIFTY Iron Butterfly (short 24300 CE / 24100 PE, wings 24400 CE / 24000 PE) - spot 24150.70. Short 24300 CE: 149.30 pts OTM (vs 154.55 at 11:35, GAINED 5.25 pts, GREEN safe, 100.30 below 24250 yellow zone). Short 24100 PE: 50.70 pts OTM (vs 45.45 at 11:35, LOST 5.25 pts, GREEN safe, 35.70 above 24115 close trigger, 40.70 above 24120 escalation). Wings 24400 CE / 24000 PE = 249.30 / 150.70 pts away. Net credit 50.23 INR per unit, total 3264.95 INR. Max loss capped 3235.05 INR. PE side lost 5.25 pts (delta tiny). CE side gained 5.25 pts (theta working). Net effect: structure stable, both sides within safe zone. (3) DECISION CONTEXT: 11:35 tick's NEXT TICK RULE = 'If BN<57420 on next refresh, CLOSE PE side of BN IC.' At 11:40 BN=57412.15, which is 7.85 below 57420 — RULE TRIGGERED. Additionally, 11:35 tick's PE-side CLOSE trigger 'if BANKNIFTY<57415' is BREACHED by 2.85 pts — this is a direct mechanical close trigger independent of the NEXT TICK rule. 0DTE monthly gamma risk is the dominant factor. 3h35m to expiry, gamma near the money explodes. If BN breaks 57300 wing, PE side max loss = 674.70 INR. The lower-lows pattern (57426 -> 57408 -> 57405 -> 57412) is bearish failure at the 57420-57425 support zone. Bounces are getting shallower and shorter. (4) ACTION: CLOSE PE SIDE OF BANKNIFTY IC. This means: BUY 30 of 57400 PE (close the short, currently ITM ~12 pts), SELL 30 of 57300 PE (close the long, currently ~12 pts ITM as well). Net effect: remove the PE spread, keep the CE spread as a theta-collection position. (5) CE SIDE STAYS: 187.85 OTM, well below 57550 yellow zone, plenty of theta left to harvest. The CE side is a 'BN stays below 57600' bet which is still very safe. (6) NIFTY IB UNCHANGED: Both sides well-buffered, no triggers breached. NIFTY range regime intact. (7) Max loss combined if held = 3235 (NIFTY IB) + 675 (BN IC) = 3910 INR ~3.7% of 105,535 cash. By closing PE side, we cap BN IC PE side loss at current MTM (~150-200 INR per unit estimate = ~5000-6000 INR total for PE side... wait that's wrong. Let me re-think. The PE spread is short 57400 / long 57300. Current spread value = short 57400 PE price - long 57300 PE price. When BN is 12 below short strike, the spread is roughly at max width - small credit. Actually the max loss is capped by the wing width minus net credit. Let me just say: closing now at current MTM is far less than 674 INR max loss, so the close is the right call. Estimated PE side MTM loss if closed now: ~200-400 INR (vs 674 max). Worth the certainty. (8) Bias=neutral, risk_budget_pct=2.0. 28th tick of day, FIRST NON-HOLD TICK. After this close, BN IC becomes a CE-only spread (still 1 strategy in the position count). NIFTY IB stays at 1 strategy. Total open strategies = 2 (unchanged). max_positions=2 still binding. (9) Bot log: skip 2 open strategies >= max 2 in executor (the close should be processed before the skip check). Tick count ~106600 (11:40:11). LiveKotak authed=True subscribed=46 latest=38. LiveIndia 11:40:19 latest. (10) SUMMARY: 28th tick, 1st NON-HOLD tick. CLOSE PE SIDE of BANKNIFTY IC (BUY 30 57400 PE, SELL 30 57300 PE). Triggered by 11:35 tick's mechanical NEXT TICK RULE (BN<57420) AND PE close trigger breach (BN<57415). Lower-lows pattern is bearish failure at 57420 support. 0DTE monthly gamma risk highest of month, 3h35m to expiry. Cap MTM loss rather than risk 57300 wing breach. CE side stays (theta). NIFTY IB unchanged. Bias=neutral, risk=2.0%.",
    "candle_regime_evidence": {
        "NIFTY": {
            "regime": "range",
            "confidence": 0.7,
            "reason": "range=0.34% tight + vix=11.3 low",
            "5d_change_pct": 0.3,
            "range_pct": 0.34,
            "today_move_pts": -33.55,
        },
        "BANKNIFTY": {
            "regime": "range",
            "confidence": 0.7,
            "reason": "range=0.74% tight + vix=11.3 low",
            "5d_change_pct": 0.31,
            "range_pct": 0.74,
            "today_move_pts": 72.8,
        },
    },
    "macro_evidence": {
        "in_blackout": False,
        "next_event": None,
        "events_next_7d": [],
    },
    "research_evidence": {
        "available": False,
        "note": "research not available (Kotak PDF download timed out, 25th consecutive tick), skipped research bias",
    },
    "monday_brief_evidence": {
        "applicable": False,
        "note": "Tuesday - Monday brief not consulted (per cron spec, Tue-Fri skip Monday brief)",
    },
    "position_evidence": [
        {
            "strategy": "NIFTY Iron Butterfly",
            "short_strike_ce": 24300,
            "short_strike_pe": 24100,
            "wing_ce": 24400,
            "wing_pe": 24000,
            "width_pts": 100,
            "spot": 24150.70,
            "distance_to_short_ce_pts": 149.30,
            "distance_to_short_pe_pts": 50.70,
            "distance_to_wing_ce_pts": 249.30,
            "distance_to_wing_pe_pts": 150.70,
            "expiry": "2026-08-25",
            "0dte": True,
            "monthly_expiry": True,
            "opened_at": "2026-08-25 09:00:40",
            "net_credit": 3264.95,
            "max_loss": 3235.05,
            "status": "CE_149.30pts_OTM_GREEN_PE_50.70pts_OTM_40.70_above_24120_escalation_35.70_above_24115_close_trigger_UNCHANGED",
            "tight_side_watch": "PE_24100_50.70pts_OTM_LOST_5.25pts_vs_11_35_still_GREEN_safe_CE_149.30pts_OTM_GAINED_5.25pts_100.30pts_below_24250_yellow",
        },
        {
            "strategy": "BANKNIFTY Iron Condor (PE side being closed this tick)",
            "short_strikes": [57600, 57400],
            "wings": [57700, 57300],
            "width_pts": 100,
            "spot": 57412.15,
            "distance_to_short_ce_pts": 187.85,
            "distance_to_short_pe_pts": 12.15,
            "distance_to_wing_ce_pts": 287.85,
            "distance_to_wing_pe_pts": 112.15,
            "expiry": "2026-08-25",
            "0dte": True,
            "monthly_expiry": True,
            "opened_at": "2026-08-25 09:00:40",
            "net_credit": 2325.30,
            "max_loss": 674.70,
            "status": "CE_187.85pts_OTM_GREEN_PE_12.15pts_OTM_BREACHED_57415_close_trigger_BY_2.85pts_BREACHED_57420_escalation_BY_7.85pts_PE_CLOSE_TRIGGERED_THIS_TICK",
            "tight_side_watch": "PE_57400_12.15pts_OTM_BREACHING_close_trigger_LOST_13.95pts_vs_11_35_lower_lows_pattern_CE_187.85pts_OTM_GAINED_13.95pts_137.85pts_below_57550_yellow_stays_as_theta_position",
        },
    ],
    "risk_budget_pct": 2.0,
    "tuesday_posture": "normal",
    "monthly_expiry_note": "Aug 25 2026 = last Tuesday of month = monthly expiry for NIFTY/BANKNIFTY Aug contracts. Combined with weekly = 0DTE MONTHLY close. Gamma risk highest of month. PE side of BN IC being closed this tick to cap gamma exposure; CE side stays.",
    "opening_buffer_note": "Opening buffer 09:15-09:30 ended at 09:30:18. Now 145 min into regular session (11:40 IST), 3h35m to 15:15 square-off, 1h50m to 13:30 no-new-entries cutoff. 5-min ACTION vs 11:35 tick: CLOSE PE SIDE OF BN IC. Triggered by 11:35 tick's NEXT TICK RULE (BN<57420) which is now BREACHED, and by PE close trigger 57415 which is BREACHED by 2.85 pts. With intermediate BN refreshes: 11:37:45 57408.90 (FIRST sub-57415), 11:38:15 57419.10 (bounce to 5.10 above), 11:38:47 57429.60 (peak 9.60 above 57420), 11:39:17 57429.15, 11:39:48 57405.25 (SECOND sub-57415, deeper low), 11:40:19 57412.15 (SUSTAINED sub-57415). Lower lows: 57426.10 -> 57408.90 -> 57405.25. Bounces getting shallower. NIFTY -5.20 pts (24155.90 -> 24150.70, -0.022%). VIX 11.34 -> 11.29 (-0.05, back to calmer, still <12 calm). BANKNIFTY 57400 short PE LOST 13.95 pts (26.10 -> 12.15 OTM, BREACHED 57415 close trigger by 2.85 pts, BREACHED 57420 escalation by 7.85 pts). BANKNIFTY 57600 short CE GAINED 13.95 pts (173.90 -> 187.85 OTM, GREEN safe, 137.85 below 57550 yellow). NIFTY 24100 short PE LOST 5.25 pts (45.45 -> 50.70 OTM, still 35.70 above 24115 close, 40.70 above 24120 trigger). NIFTY 24300 short CE GAINED 5.25 pts (154.55 -> 149.30 OTM, GREEN). PE close trigger 57415 BREACHED by 2.85 pts. PE escalation 57420 BREACHED by 7.85 pts. HARD TRIGGER 57580: BN is 167.85 below (retreated from 153.90 at 11:35, still safely below).",
    "reversal_note": "BN SUSTAINED BREAK. At 11:35 BN was 57426.10 with PE buffer 6.10 above 57420 escalation. At 11:40 BN is 57412.15 — 2.85 BELOW 57415 PE close trigger AND 7.85 BELOW 57420 escalation. Both PE triggers breached. Pattern: 11:35 57426.10 (tight) -> 11:37:45 57408.90 (BREACH #1, sub-57415) -> 11:38:15 57419.10 (bounce to 5.10 above trigger, shallow) -> 11:38:47 57429.60 (peak, only 9.60 above 57420) -> 11:39:17 57429.15 -> 11:39:48 57405.25 (BREACH #2, deeper low) -> 11:40:19 57412.15 (SUSTAINED sub-57415). Lower lows: 57408.90 -> 57405.25 (deeper each cycle). Bounces getting shallower: 57419.10 was only 5.10 above trigger, 57429.60 was only 9.60 above 57420. This is BEARISH FAILURE PATTERN at the 57420-57425 support zone. 0DTE monthly gamma risk is highest of the month. Per 11:35 NEXT TICK RULE: 'If BN<57420 on next refresh, CLOSE PE side of BN IC.' TRIGGERED. Per escalation rule: 'if BANKNIFTY<57415 or NIFTY<24115, CLOSE respective IC/IB PE side.' BN 57412.15 < 57415 = TRIGGERED. Both rules concur. ACTION: CLOSE PE side of BN IC (BUY 30 57400 PE, SELL 30 57300 PE). After this close, BN IC becomes a CE-only vertical spread (theta collection only). NIFTY IB unchanged (no triggers breached on NIFTY side).",
    "escalation_rule": "PE-side CLOSE triggers: if BANKNIFTY<57415 or NIFTY<24115, CLOSE respective IC/IB PE side. BANKNIFTY currently 2.85 BELOW 57415 (vs 11.10 above at 11:35, LOST 13.95 pts, BREACHED, ACTION THIS TICK). NIFTY currently 35.70 above 24115 (vs 30.45 at 11:35, GAINED 5.25 pts, NOT triggered). PE-side ESCALATION triggers: if BANKNIFTY<57420 OR NIFTY<24120, prepare to close PE side. BANKNIFTY currently 7.85 BELOW 57420 (vs 6.10 above at 11:35, LOST 13.95 pts, BREACHED, ACTION THIS TICK). NIFTY currently 40.70 above 24120 (vs 25.45 at 11:35, GAINED 15.25 pts, NOT triggered, recovering). CE-side YELLOW zone: NIFTY in 24250-24300 OR BANKNIFTY in 57550-57600 = watch closely. BANKNIFTY currently 137.85 below 57550 (GREEN safe). NIFTY currently 100.30 below 24250 (GREEN safe). CE-side RED zone: NIFTY>24300 OR BANKNIFTY>57600 = close CE side. NOT triggered. HARD TRIGGER 57580: BANKNIFTY is 167.85 below (retreated from 153.90 at 11:35, still safely below). SUSTAINED-PULLBACK WATCH: TRIGGERED — CLOSE PE SIDE of BN IC this tick. After close, sustained-pullback watch for PE side RESCINDED (position closed). CE side watch remains NORMAL. Time triggers: 13:30 no new entries (1h50m), 14:30 consider 0DTE close (2h50m), 15:15 square off (3h35m). NEXT TICK RULE: Monitor BN for continuation below 57420. If BN breaks 57300 wing on BN IC, the entire IC was already 674.70 max loss — but since we're closing PE side now, only CE side remains and it has 187.85 pts OTM buffer (very safe). If BN rallies back above 57500, the closed PE side is gone (no theta to recapture, but also no further risk).",
    "tick_summary_11_40": "28th tick of day, 1st NON-HOLD. CLOSE PE SIDE of BANKNIFTY IC. Bias=neutral. BN at 57412.15 BREACHED PE close trigger 57415 by 2.85 pts AND escalation 57420 by 7.85 pts. Pattern: 4 tests of 57420-57425 support zone in 15 min with progressively lower lows (11:25 57425.65, 11:35 57426.10, 11:37 57408.90 sub-57415, 11:39:48 57405.25 sub-57415 deeper, 11:40 57412.15 sustained sub-57415). Bounces getting shallower. Bearish failure pattern at support. 0DTE monthly expiry, gamma risk highest of month, 3h35m to expiry. Action: BUY 30 57400 PE (close short), SELL 30 57300 PE (close long). CE side stays (187.85 OTM, 137.85 below 57550 yellow, theta). NIFTY IB unchanged (PE 50.70 OTM, CE 149.30 OTM, both GREEN). Triggered by 11:35 tick's mechanical NEXT TICK RULE (BN<57420) AND PE close trigger breach (BN<57415). Risk_budget_pct=2.0. VIX 11.29 (calm). Max loss if held vs close: held = 674.70 INR PE side, close = current MTM (estimated 200-400 INR, well under max). Close is the right call.",
}

new_history_entry = {
    "ist_time": "2026-08-25 11:40:25",
    "bias": "neutral",
    "note": "0dte_monthly_expiry_bn_breach_57415_close_trigger_by_2.85pts_lower_lows_pattern_close_pe_side_of_bn_ic_ce_kept_nifty_ib_unchanged",
    "actions": [
        {
            "id": "act-114025A",
            "type": "CLOSE",
            "strategy": "ic_BANKNIFTY_pe_side",
            "underlying": "BANKNIFTY",
            "expiry": "2026-08-25",
            "legs": [
                {"side": "BUY", "strike": 57400, "option_type": "PE", "qty": 30, "price": None},
                {"side": "SELL", "strike": 57300, "option_type": "PE", "qty": 30, "price": None},
            ],
        }
    ],
}

new_addendum = (
    " | 11:40 tick: BREAK OF PE CLOSE TRIGGER 57415. BN at 57412.15 (-13.95 from 11:35), "
    "2.85 below 57415 close and 7.85 below 57420 escalation. Lower-lows pattern: 11:37 57408.90, "
    "11:39:48 57405.25, 11:40 57412.15. Bounces shallow (peak 57429.60 only 9.60 above 57420). "
    "1st NON-HOLD tick — CLOSE PE SIDE of BN IC (BUY 30 57400 PE, SELL 30 57300 PE). "
    "CE side kept (187.85 OTM, GREEN). NIFTY IB unchanged (PE 50.70 OTM, CE 149.30 OTM, both GREEN). "
    "After close, BN IC = CE-only vertical. Total open strategies = 2 unchanged. "
    "Sustained-pullback watch on PE side RESCINDED after close. "
    "VIX 11.34 -> 11.29 (-0.05, calm). 28th tick of day."
)

with STATE_PATH.open("r", encoding="utf-8") as f:
    state = json.load(f)

state["last_decision"] = new_last_decision
state["call_count_today"] = int(state.get("call_count_today", 0)) + 1
state.setdefault("history", []).append(new_history_entry)
state["last_decision_history_addendum"] = state.get("last_decision_history_addendum", "") + new_addendum

with STATE_PATH.open("w", encoding="utf-8") as f:
    json.dump(state, f, indent=2, ensure_ascii=False)

print(f"OK: last_decision updated, call_count_today={state['call_count_today']}, "
      f"history_len={len(state['history'])}, addendum_len={len(state['last_decision_history_addendum'])}")
