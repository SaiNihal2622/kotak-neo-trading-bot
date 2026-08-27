#!/usr/bin/env python3
"""Surgically update last_decision in brain_state.json, preserving everything else."""
import json
import sys
from datetime import datetime, timezone, timedelta

STATE_PATH = r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json"

# IST = UTC+5:30
ist = timezone(timedelta(hours=5, minutes=30))
now_utc = datetime.now(timezone.utc)
now_ist = now_utc.astimezone(ist)
ts_utc = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
ts_ist = now_ist.strftime("%Y-%m-%d %H:%M:%S")

new_decision = {
    "ts": ts_utc,
    "ist_time": ts_ist,
    "bias": "neutral",
    "source": "mavis",
    "max_positions": 2,
    "actions": [],
    "note": "0dte_monthly_expiry_bn_bounced_+37pts_to_57462_pe_buffer_recovered_to_47.65pts_above_57415_close_42.65pts_above_57420_escalation_vix_11.19_calmest_hold",
    "reasoning": "Tick at 11:30 IST on Tue 2026-08-25 (0DTE MONTHLY expiry day). 5 min after 11:25 tick, 135 min into regular session (past 09:30 opening buffer), 3h45m to 15:15 square-off, 2h to 13:30 no-new-entries cutoff. Market in regular session. VIX 11.1975 (essentially flat from 11.185 at 11:25, +0.0125; still <12 very low, calm regime, theta friendly). Range regime confirmed for both underlyings (NIFTY conf=0.7 range=0.34%, BANKNIFTY conf=0.7 range=0.74%, unchanged). Macro: no events next 7d, no blackout (in_blackout=false). Research: still unavailable (Kotak PDF timed out, 23rd consecutive tick - skip research bias). Live positions: 2 strategies (NIFTY IB + BANKNIFTY IC) at max_positions=2. STATUS UPDATE vs 11:25: BN REVERSAL +37.00 pts BOUNCE (57425.65 -> 57462.65, +0.064%, +0.64 sigma). LiveIndia refreshes since 11:25: 11:27:56 NF=24149.50 BN=57443.10 VIX=11.29, 11:28:56 NF=24150.05 BN=57463.50 VIX=11.27, 11:29:27 NF=24149.50 BN=57443.10 VIX=11.29, 11:29:58 NF=24149.55 BN=57450.85 VIX=11.28, 11:30:30 NF=24151.40 BN=57462.65 VIX=11.19. BANKNIFTY: 11:25 57425.65 -> 11:27:56 57443.10 (+17.45) -> 11:28:56 57463.50 (+20.40 PEAK) -> 11:29:27 57443.10 (-20.40 pullback) -> 11:29:58 57450.85 (+7.75) -> 11:30:30 57462.65 (+11.80 settled). This is OSCILLATION pattern 57443-57463, with the latest reading 57462.65 strongly above the 11:25 low. NIFTY drifted -2.05 pts (24153.45 -> 24151.40, -0.008%, basically flat). VIX 11.185 -> 11.1975 (+0.0125, basically flat). (1) NIFTY Iron Butterfly (short 24300 CE / 24100 PE, wings 24400 CE / 24000 PE) - spot 24151.40. Short 24300 CE: 148.60 pts OTM (vs 11:25 146.55, GAINED 2.05 pts, GREEN safe, 98.40 below 24250 yellow zone, 0.61% of spot). Short 24100 PE: 51.40 pts OTM (vs 11:25 53.45, LOST 2.05 pts, GREEN safe, 31.40 above 24120 escalation trigger, 36.40 above 24115 close trigger). Wings 24400 CE / 24000 PE = 248.60 / 151.40 pts away. Net credit 50.23 INR per unit, total 3264.95 INR. Max loss capped 3235.05 INR. PE side lost 2.05 pts (delta tiny against us), CE side gained 2.05 pts (theta working). Net effect: structure stable, both sides within safe zone. (2) BANKNIFTY Iron Condor (short 57600 CE / 57400 PE, wings 57700 CE / 57300 PE) - spot 57462.65. Short 57600 CE: 137.35 pts OTM (vs 11:25 174.35, LOST 37.00 pts, GREEN safe, 87.35 below 57550 yellow zone). Short 57400 PE: 62.65 pts OTM (vs 11:25 25.65, GAINED 37.00 pts! RECOVERY, GREEN safe, 47.65 above 57415 close trigger, 42.65 above 57420 escalation trigger - BUFFER RECOVERED FROM TIGHTEST OF DAY). Wings 57700 CE / 57300 PE = 237.35 / 162.65 pts away. Net credit 77.51 INR per unit, total 2325.30 INR. Max loss capped 674.70 INR. CE side LOST 37.00 pts (delta working against us). PE side GAINED 37.00 pts (theta winning). Net structure: still net positive on theta, PE buffer recovered to comfortable. (3) MTM if closed now: NIFTY IB still net positive on theta. BANKNIFTY IC recovered from morning tightness. (4) Combined max loss if both breached = 3235 + 675 = 3910 INR ~3.7% of 105,535 cash. UNCHANGED. (5) DECISION CONTEXT: BN bounce +37.00 pts in 5 minutes is significant. Today intraday BN range = 57231.25 to 57653.85 (422 pts). Current 57462.65 at 50th percentile (recovered to middle of range from 47th at 11:25). NIFTY intraday range = 24115.45 to 24198.25 (83 pts). Current 24151.40 at 43rd percentile. Both within range bounds. The oscillation pattern (57443-57463) suggests the morning low of 57417.75 was a wick, not a sustained break. The 11:28:56 peak of 57463.50 is approaching the 11:20 reading of 57435.75+27.75 - the 11:20 drift was transient. Range regime intact. (6) ESCALATION RULES check: PE-side CLOSE: if BANKNIFTY<57415 or NIFTY<24115 -> BN currently 47.65 above 57415 (vs 10.65 at 11:25, EXPANDED 37.00 pts, NOT triggered, comfortable 47-pt buffer). NIFTY 36.40 above 24115 (vs 38.45 at 11:25, LOST 2.05 pts, 36-pt buffer). PE-side ESCALATION: if BANKNIFTY<57420 -> BN currently 42.65 above 57420 (vs 5.65 at 11:25, EXPANDED 37.00 pts, NOT triggered, comfortable 42-pt buffer). NIFTY 31.40 above 24120 (vs 33.45 at 11:25, LOST 2.05 pts, 31-pt buffer). CE-side YELLOW zone: NIFTY in 24250-24300 OR BANKNIFTY in 57550-57600 -> NOT triggered. CE-side RED zone: NIFTY>24300 OR BANKNIFTY>57600 -> NOT triggered. HARD TRIGGER 57580: BN is 117.35 below (retreated from 154.35 at 11:25, still safely below). (7) NO ACTION rationale: All triggers safely NOT breached with comfortable buffers. PE close trigger 57415 has 47.65 pts buffer (vs 10.65 at 11:25 - major recovery). PE escalation 57420 has 42.65 pts buffer (vs 5.65 at 11:25 - recovered to comfortable). Range regime confirmed. 0DTE monthly expiry theta accelerating (3h45m to expiry). Max loss capped 3910 INR. VIX 11.1975 (still very low). The 11:25 tight-of-day compression was a transient wick, fully recovered. Sustained-pullback watch DE-ESCALATED to normal monitoring. (8) Bias=neutral, risk_budget_pct=2.0. (9) Bot log: skip 2 open strategies >= max 2 correctly blocking. Tick count 101350+ (11:28:44). LiveKotak authed=True subscribed=46 latest=38 (healthy). LiveIndia 11:30:30 latest. (10) SUMMARY: 26th HOLD tick of the day. Bias=neutral. BN RECOVERY: +37.00 pts in 5 min, PE buffer RECOVERED from 5.65 above 57420 escalation (TIGHTEST OF DAY at 11:25) to 42.65 pts (comfortable). NIFTY -2.05 pts (basically flat). VIX 11.1975 (calm). Last 5 refreshes: NF 24149.50-24151.40 (1.90 pts range, super tight), BN 57443.10-57463.50 (20.40 pts range, mild oscillation). BANKNIFTY 57400 short PE EXPANDED 37.00 pts (25.65 -> 62.65 OTM, RECOVERY, 47.65 above 57415 close, 42.65 above 57420 escalation - comfortable). BANKNIFTY 57600 short CE COMPRESSED 37.00 pts (174.35 -> 137.35 OTM, still GREEN safe, 87.35 below 57550 yellow zone). NIFTY 24100 PE lost 2.05 pts (53.45 -> 51.40 OTM, still 36.40 above 24115 close). NIFTY 24300 CE gained 2.05 pts (146.55 -> 148.60 OTM, GREEN). Buffer migration: BN PE gained 37.00 pts (theta winning back), BN CE lost 37.00 pts (delta working against us but still safe). Range regime intact, 0DTE monthly expiry theta working. Max loss combined 3,910 INR (3.7% cash) unchanged. HARD TRIGGER 57580 retreated to 117.35 below. PE close trigger 57415 has 47.65 pts buffer (NOT breached, recovered). PE escalation 57420 has 42.65 pts buffer (NOT breached, comfortable). 26th HOLD tick. NIFTY at 43rd percentile, BANKNIFTY at 50th percentile of today range - both within range bounds. Sustained-pullback watch DE-ESCALATED to normal monitoring. Let theta continue working through the rest of the session. Monitor for any new sustained break. If PE buffer drops below 10 pts OR escalation 57420 is breached, will re-escalate.",
    "candle_regime_evidence": {
        "NIFTY": {
            "regime": "range",
            "confidence": 0.7,
            "reason": "range=0.34% tight + vix=11.2 low",
            "5d_change_pct": 0.3,
            "range_pct": 0.34,
            "today_move_pts": -33.55
        },
        "BANKNIFTY": {
            "regime": "range",
            "confidence": 0.7,
            "reason": "range=0.74% tight + vix=11.2 low",
            "5d_change_pct": 0.31,
            "range_pct": 0.74,
            "today_move_pts": 72.8
        }
    },
    "macro_evidence": {
        "in_blackout": False,
        "next_event": None,
        "events_next_7d": []
    },
    "research_evidence": {
        "available": False,
        "note": "research not available (Kotak PDF download timed out, 23rd consecutive tick), skipped research bias"
    },
    "monday_brief_evidence": {
        "applicable": False,
        "note": "Tuesday - Monday brief not consulted (per cron spec, Tue-Fri skip Monday brief)"
    },
    "position_evidence": [
        {
            "strategy": "NIFTY Iron Butterfly",
            "short_strike_ce": 24300,
            "short_strike_pe": 24100,
            "wing_ce": 24400,
            "wing_pe": 24000,
            "width_pts": 100,
            "spot": 24151.4,
            "distance_to_short_ce_pts": 148.6,
            "distance_to_short_pe_pts": 51.4,
            "distance_to_wing_ce_pts": 248.6,
            "distance_to_wing_pe_pts": 151.4,
            "expiry": "2026-08-25",
            "0dte": True,
            "monthly_expiry": True,
            "opened_at": "2026-08-25 09:00:40",
            "net_credit": 3264.95,
            "max_loss": 3235.05,
            "status": "CE_148.60pts_OTM_GREEN_PE_51.40pts_OTM_31.40_above_24120_trigger_36.40_above_24115_close_trigger",
            "tight_side_watch": "PE_24100_OUTSIDE_YELLOW_zone_31.40pts_above_24120_trigger_36.40pts_close_buffer_LOST_2.05pts_vs_11_25_CE_GAINED_2.05pts"
        },
        {
            "strategy": "BANKNIFTY Iron Condor",
            "short_strikes": [57600, 57400],
            "wings": [57700, 57300],
            "width_pts": 100,
            "spot": 57462.65,
            "distance_to_short_ce_pts": 137.35,
            "distance_to_short_pe_pts": 62.65,
            "distance_to_wing_ce_pts": 237.35,
            "distance_to_wing_pe_pts": 162.65,
            "expiry": "2026-08-25",
            "0dte": True,
            "monthly_expiry": True,
            "opened_at": "2026-08-25 09:00:40",
            "net_credit": 2325.3,
            "max_loss": 674.7,
            "status": "CE_137.35pts_OTM_GREEN_PE_62.65pts_OTM_47.65_above_57415_close_trigger_42.65_above_57420_escalation_trigger",
            "tight_side_watch": "PE_57400_BUFFER_RECOVERED_47.65pts_above_57415_close_42.65pts_above_57420_escalation_FROM_TIGHTEST_OF_DAY_AT_11_25_GAINED_37.00pts_CE_LOST_37.00pts_THETA_WIN_PE"
        }
    ],
    "risk_budget_pct": 2.0,
    "tuesday_posture": "normal",
    "monthly_expiry_note": "Aug 25 2026 = last Tuesday of month = monthly expiry for NIFTY/BANKNIFTY Aug contracts. Combined with weekly = 0DTE MONTHLY close. Gamma risk highest of month. Hold short-vol structures; do not add.",
    "opening_buffer_note": "Opening buffer 09:15-09:30 ended at 09:30:18. Now 135 min into regular session, 3h45m to square-off. 5-min ACTION vs 11:25 tick: BN BOUNCE +37.00 pts (57425.65 -> 57462.65, +0.064%), with intermediate oscillation: 11:27:56 57443.10 (+17.45), 11:28:56 57463.50 (+37.85 PEAK), 11:29:27 57443.10 (-20.40 pullback), 11:29:58 57450.85 (+7.75), 11:30:30 57462.65 (+11.80 settled). NIFTY -2.05 pts (24153.45 -> 24151.40, -0.008%). VIX 11.185 -> 11.1975 (+0.0125, flat). Last 5 refreshes: NF 24149.50-24151.40 (1.90 pts range, super tight), BN 57443.10-57463.50 (20.40 pts range). NIFTY 24100 short PE LOST 2.05 pts buffer (53.45 -> 51.40 OTM, still 36.40 above 24115 close). NIFTY 24300 short CE GAINED 2.05 pts (146.55 -> 148.60 OTM, GREEN). BANKNIFTY 57400 short PE EXPANDED 37.00 pts (25.65 -> 62.65 OTM, RECOVERY FROM TIGHTEST OF DAY, now 47.65 above 57415 close, 42.65 above 57420 escalation - comfortable). BANKNIFTY 57600 short CE COMPRESSED 37.00 pts (174.35 -> 137.35 OTM, still GREEN, 87.35 below 57550 yellow zone). Hard trigger 57580 retreated to 117.35 below. PE close trigger 57415 has 47.65 pts buffer (RECOVERED +37 pts, NOT breached). PE escalation 57420 has 42.65 pts buffer (RECOVERED +37 pts, NOT breached, comfortable).",
    "reversal_note": "BN REVERSAL CONFIRMED. At 11:25 BN was 57425.65 with PE buffer 5.65 above 57420 escalation (TIGHTEST OF DAY). At 11:30:30 BN is 57462.65 with PE buffer 42.65 above 57420 escalation (RECOVERED). The 11:25 low was a transient wick, not a sustained break. Oscillation pattern 57443-57463 over 5 minutes confirms range-bound behavior, not directional. Today intraday BN range = 57231.25 to 57653.85 (422 pts). Current 57462.65 at 50th percentile (recovered to middle from 47th at 11:25). PE side of IC structure has now RECOVERED its buffer from tight-of-day. CE side has lost 37.00 pts (delta working against us) but still 137.35 OTM and 87.35 below 57550 yellow zone - GREEN safe. Net structure: still net positive on theta, with PE buffer comfortable. Sustained-pullback watch DE-ESCALATED from INTENSIFIED (11:25) to NORMAL MONITORING. Hold. If PE buffer drops below 10 pts OR escalation 57420 is breached on next refresh, will re-escalate. Note: the 11:28:56 peak of 57463.50 was a single refresh - this is a wider oscillation but still within range. The 11:25 5-min compression to 5.65 above escalation was an extreme wick (2.75 below 57420 was at 11:23:48 BN=57417.75). Such wicks are normal in low-VIX range-bound days and recovered quickly.",
    "escalation_rule": "PE-side CLOSE triggers (UNCHANGED): if BANKNIFTY<57415 or NIFTY<24115, CLOSE respective IC/IB PE side. BANKNIFTY currently 47.65 above 57415 (vs 10.65 at 11:25, EXPANDED 37.00 pts, NOT triggered, comfortable 47-pt buffer). NIFTY currently 36.40 above 24115 (vs 38.45 at 11:25, LOST 2.05 pts, 36-pt buffer). PE-side ESCALATION triggers: if BANKNIFTY<57420 OR NIFTY<24120, prepare to close PE side. BANKNIFTY currently 42.65 above 57420 (vs 5.65 at 11:25, EXPANDED 37.00 pts, NOT triggered, comfortable 42-pt buffer). NIFTY currently 31.40 above 24120 (vs 33.45 at 11:25, LOST 2.05 pts, 31-pt buffer). CE-side YELLOW zone: NIFTY in 24250-24300 OR BANKNIFTY in 57550-57600 = watch closely. BANKNIFTY currently 87.35 below 57550 (GREEN safe). NIFTY currently 98.40 below 24250 (GREEN safe). CE-side RED zone: NIFTY>24300 OR BANKNIFTY>57600 = close CE side. NOT triggered. HARD TRIGGER 57580: BANKNIFTY is 117.35 below (retreated from 154.35 at 11:25). Sustained-pullback watch DE-ESCALATED to NORMAL (BN recovered 57443-57463 oscillation, no sustained break). Time triggers: 13:30 no new entries (2h), 14:30 consider 0DTE close (3h), 15:15 square off (3h45m).",
    "tick_summary_11_30": "26th HOLD tick of the day. Bias=neutral. BN RECOVERY BOUNCE +37.00 pts in 5 min, PE BUFFER RECOVERED from 5.65 above 57420 escalation (TIGHTEST OF DAY at 11:25) to 42.65 pts (comfortable). NIFTY -2.05 pts (24153.45 -> 24151.40, -0.008%, basically flat). BANKNIFTY +37.00 pts (57425.65 -> 57462.65, +0.064%, +0.64 sigma). VIX 11.185 -> 11.1975 (+0.0125, flat, still <12 calmest of day). Last 5 refreshes: NF 24149.50-24151.40 (1.90 pts range, super tight), BN 57443.10-57463.50 (20.40 pts range, mild oscillation). BANKNIFTY 57400 short PE EXPANDED 37.00 pts (25.65 -> 62.65 OTM, RECOVERY, now 47.65 above 57415 close - recovered, 42.65 above 57420 escalation - comfortable). BANKNIFTY 57600 short CE COMPRESSED 37.00 pts (174.35 -> 137.35 OTM, still GREEN safe, 87.35 below 57550 yellow zone). NIFTY 24100 PE lost 2.05 pts (53.45 -> 51.40 OTM, 36.40 above 24115 close). NIFTY 24300 CE gained 2.05 pts (146.55 -> 148.60 OTM, GREEN). Buffer migration: BN PE gained 37.00 pts (theta winning back), BN CE lost 37.00 pts (delta working against us but still safe). Range regime intact, 0DTE monthly expiry theta working. Max loss combined 3,910 INR (3.7% cash) unchanged. HARD TRIGGER 57580 retreated to 117.35 below. PE close trigger 57415 has 47.65 pts buffer (RECOVERED +37 pts, NOT breached). PE escalation 57420 has 42.65 pts buffer (RECOVERED +37 pts, NOT breached, comfortable). Sustained-pullback watch DE-ESCALATED to NORMAL monitoring. 26th HOLD tick. NIFTY at 43rd percentile, BANKNIFTY at 50th percentile of today range - both within range bounds. All triggers safely NOT breached. Let theta continue working through the rest of the session. Monitor for any new sustained break. If PE buffer drops below 10 pts OR escalation 57420 is breached, will re-escalate."
}

# Load state
with open(STATE_PATH, "r", encoding="utf-8") as f:
    state = json.load(f)

# Save old ist_time for addendum
old_ist = state["last_decision"].get("ist_time", "unknown")
old_note = state["last_decision"].get("note", "")

# Append to addendum
addendum_old = state.get("last_decision_history_addendum", "")
addendum_new = f"| {ts_ist} tick (26th): {new_decision['note']} | previous: {old_ist} {old_note}"
state["last_decision_history_addendum"] = addendum_old + "\n" + addendum_new

# Replace last_decision
state["last_decision"] = new_decision

# Update call_count_today
state["call_count_today"] = state.get("call_count_today", 0) + 1

# Append to history
if "history" not in state:
    state["history"] = []
state["history"].append({
    "ist_time": ts_ist,
    "bias": "neutral",
    "note": new_decision["note"],
    "actions": []
})

# Write back
with open(STATE_PATH, "w", encoding="utf-8") as f:
    json.dump(state, f, ensure_ascii=False, indent=2)

print(f"OK: last_decision updated to {ts_ist}, call_count_today={state['call_count_today']}, history size={len(state['history'])}")
print(f"old: {old_ist}")
print(f"new: {ts_ist}")
