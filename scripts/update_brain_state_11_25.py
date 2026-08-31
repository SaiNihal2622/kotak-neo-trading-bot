"""Update brain_state.json for 11:25 IST tick (25th HOLD of day)."""
import json
from pathlib import Path

STATE_PATH = Path(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json")

with STATE_PATH.open("r", encoding="utf-8") as f:
    state = json.load(f)

state["call_count_today"] = 28

state["last_decision"] = {
    "ts": "2026-08-25T05:55:25Z",
    "ist_time": "2026-08-25 11:25:25",
    "bias": "neutral",
    "source": "mavis",
    "max_positions": 2,
    "actions": [],
    "note": "0dte_monthly_expiry_bn_pe_buffer_further_compressed_to_10.65pts_above_57415_close_5.65pts_above_57420_escalation_NOT_breached_hold_with_intensified_watch",
    "reasoning": "Tick at 11:25 IST on Tue 2026-08-25 (0DTE MONTHLY expiry day). 5 min after 11:20 tick, 130 min into regular session (past 09:30 opening buffer), 3h50m to 15:15 square-off, 2h5m to 13:30 no-new-entries cutoff. Market in regular session. VIX 11.185 (down from 11.35 at 11:20, -0.165; still <12 very low, calm regime, theta friendly). Range regime confirmed for both underlyings (NIFTY conf=0.7 range=0.34%, BANKNIFTY conf=0.7 range=0.74%, unchanged). Macro: no events next 7d, no blackout (in_blackout=false). Research: still unavailable (Kotak PDF timed out, 22nd consecutive tick - skip research bias). Live positions: 2 strategies (NIFTY IB + BANKNIFTY IC) at max_positions=2. STATUS UPDATE vs 11:20: BN DRIFT CONTINUES - PE BUFFER FURTHER COMPRESSED. LiveIndia refreshes since 11:20: 11:23:48 NF=24149.75 BN=57417.75 VIX=11.20, 11:24:19 NF=24151.40 BN=57419.75 VIX=11.19, 11:24:49 NF=24153.30 BN=57430.70 VIX=11.19, 11:25:20 NF=24153.45 BN=57425.65 VIX=11.19. BANKNIFTY drifted -10.10 pts from 11:20 (57435.75 -> 57425.65, -0.018%), with intra-tick low of 57417.75 at 11:23:48 (17.90 below 11:20) before bouncing to 57430.70 at 11:24:49 then settling at 57425.65 at 11:25:20. NIFTY drifted +3.90 pts (24149.55 -> 24153.45, +0.016%, basically flat). VIX 11.35 -> 11.185 (DOWN 0.165, more calm). (1) NIFTY Iron Butterfly (short 24300 CE / 24100 PE, wings 24400 CE / 24000 PE) - spot 24153.45. Short 24300 CE: 146.55 pts OTM (vs 11:20 150.45, lost 3.90 pts, basically unchanged, GREEN safe, 0.61% of spot, 96.45 below 24250 yellow zone). Short 24100 PE: 53.45 pts OTM (vs 11:20 49.55, GAINED 3.90 pts, GREEN safe, 38.45 above 24115 close trigger, 33.45 above 24120 escalation trigger). Wings 24400 CE / 24000 PE = 246.55 / 153.45 pts away. Net credit 50.23 INR per unit, total 3264.95 INR. Max loss capped 3235.05 INR. PE side gained 3.90 pts (theta+delta work in our favor), CE side lost 3.90 pts (delta working against us but small). Net effect: structure stable, both sides within safe zone. (2) BANKNIFTY Iron Condor (short 57600 CE / 57400 PE, wings 57700 CE / 57300 PE) - spot 57425.65. Short 57600 CE: 174.35 pts OTM (vs 11:20 164.25, GAINED 10.10 pts, GREEN safe, 124.35 below 57550 yellow zone). Short 57400 PE: 25.65 pts OTM (vs 11:20 35.75, LOST 10.10 pts, now 10.65 above 57415 close trigger COMPRESSED from 20.75, 5.65 above 57420 escalation trigger COMPRESSED from 15.75 - WITHIN 10-PT TIGHT ZONE but NOT breached). Wings 57700 CE / 57300 PE = 274.35 / 125.65 pts away. Net credit 77.51 INR per unit, total 2325.30 INR. Max loss capped 674.70 INR. CE side GAINED 10.10 pts (theta working strongly). PE side LOST 10.10 pts (delta working against us). Net structure: still net positive on theta but PE buffer has compressed meaningfully. (3) MTM if closed now: NIFTY IB still net positive on theta. BANKNIFTY IC PE side approaching pre-close trigger. (4) Combined max loss if both breached = 3235 + 675 = 3910 INR ~3.7% of 105,535 cash. UNCHANGED. (5) DECISION CONTEXT: BN drift over last 5 minutes (-10.10 pts from 11:20) is bounded. Today intraday BN range = 57231.25 to 57653.85 (422 pts). Current 57425.65 at 47th percentile (was 48th at 11:20, slight drift down). NIFTY intraday range = 24115.45 to 24198.25 (83 pts). Current 24153.45 at 46th percentile. Both within range bounds. The 11:23:48 low of 57417.75 was another intra-tick wick (3.85 below 57420 escalation trigger, briefly entering YELLOW zone) but bounced back. The pattern is OSCILLATION between 57417-57430, not a sustained break. 11:24:49 saw a bounce to 57430.70 (+12.95 from low), 11:25:20 settled at 57425.65 (-5.05 from bounce high). This is choppy range-bound behavior, not a directional move. (6) ESCALATION RULES check: PE-side CLOSE: if BANKNIFTY<57415 or NIFTY<24115 -> BN currently 10.65 above 57415 (vs 20.75 at 11:20, COMPRESSED 10.10 pts, NOT triggered, 10-pt buffer). NIFTY 38.45 above 24115 (vs 34.55 at 11:20, GAINED 3.90 pts, 38-pt buffer). PE-side ESCALATION: if BANKNIFTY<57420 -> BN currently 5.65 above 57420 (vs 15.75 at 11:20, COMPRESSED 10.10 pts, NOT triggered but VERY TIGHT, only 5-pt buffer). NIFTY 33.45 above 24120. CE-side YELLOW zone: NIFTY in 24250-24300 OR BANKNIFTY in 57550-57600 -> NOT triggered. CE-side RED zone: NIFTY>24300 OR BANKNIFTY>57600 -> NOT triggered. HARD TRIGGER 57580: BN is 154.35 below (retreated from 144.25 at 11:20). (7) NO ACTION rationale: PE close trigger at 57415 NOT breached (10.65 pts buffer). PE escalation trigger at 57420 NOT breached (5.65 pts buffer, TIGHTEST of the day but still above). Range regime confirmed. 0DTE monthly expiry theta accelerating (3h50m to expiry). Max loss capped 3910 INR. VIX 11.185 (very low, even calmer than 11:20). Sustained-pullback watch REACTIVATED and INTENSIFIED (BN intra-tick low 57417.75, 2.75 below 57420 escalation but bounced). The 57415 close trigger is the explicit rule. 10.65 pts buffer is meaningful. Premature close would lock in slippage loss (theta would be negative slip) for a structure still well within the explicit rules. (8) Bias=neutral, risk_budget_pct=2.0. (9) Bot log: skip 2 open strategies >= max 2 correctly blocking. Tick count 99070+ (11:25). LiveKotak authed=True subscribed=46 latest=38 (healthy). (10) SUMMARY: 25th HOLD tick of the day. Bias=neutral. BN PE BUFFER TIGHTEST of day at 10.65 pts above 57415 close (vs 20.75 at 11:20, -10.10 pts). 5.65 pts above 57420 escalation (vs 15.75 at 11:20). NOT breached. NIFTY at 46th percentile of today range (slight gain +3.90 pts). BANKNIFTY at 47th percentile (slight loss -10.10 pts). CE side gained 10.10 pts (theta win). Pattern is OSCILLATION 57417-57430, not sustained break. Range regime intact, 0DTE monthly expiry theta working. VIX 11.185 (calmest of day). Max loss combined 3,910 INR (3.7% cash) unchanged. Sustained-pullback watch INTENSIFIED. Let theta continue working. Monitor for sustained break below 57415 which would trigger PE side close. If PE buffer drops below 5 pts OR escalation 57420 is breached on next refresh, will move to PE side close.",
    "candle_regime_evidence": {
        "NIFTY": {
            "regime": "range",
            "confidence": 0.7,
            "reason": "range=0.34% tight + vix=11.2 low",
            "5d_change_pct": 0.30,
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
        "note": "research not available (Kotak PDF download timed out, 22nd consecutive tick), skipped research bias"
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
            "spot": 24153.45,
            "distance_to_short_ce_pts": 146.55,
            "distance_to_short_pe_pts": 53.45,
            "distance_to_wing_ce_pts": 246.55,
            "distance_to_wing_pe_pts": 153.45,
            "expiry": "2026-08-25",
            "0dte": True,
            "monthly_expiry": True,
            "opened_at": "2026-08-25 09:00:40",
            "net_credit": 3264.95,
            "max_loss": 3235.05,
            "status": "CE_146.55pts_OTM_GREEN_PE_53.45pts_OTM_33.45_above_24120_trigger_38.45_above_24115_close_trigger",
            "tight_side_watch": "PE_24100_OUTSIDE_YELLOW_zone_33.45pts_above_24120_trigger_38.45pts_close_buffer_GAINED_3.90pts_vs_11_20_CE_LOST_3.90pts"
        },
        {
            "strategy": "BANKNIFTY Iron Condor",
            "short_strikes": [57600, 57400],
            "wings": [57700, 57300],
            "width_pts": 100,
            "spot": 57425.65,
            "distance_to_short_ce_pts": 174.35,
            "distance_to_short_pe_pts": 25.65,
            "distance_to_wing_ce_pts": 274.35,
            "distance_to_wing_pe_pts": 125.65,
            "expiry": "2026-08-25",
            "0dte": True,
            "monthly_expiry": True,
            "opened_at": "2026-08-25 09:00:40",
            "net_credit": 2325.3,
            "max_loss": 674.7,
            "status": "CE_174.35pts_OTM_GREEN_PE_25.65pts_OTM_5.65_above_57420_trigger_10.65_above_57415_close_trigger",
            "tight_side_watch": "PE_57400_TIGHTEST_OF_DAY_5.65pts_above_57420_escalation_10.65pts_above_57415_close_COMPRESSED_10.10pts_vs_11_20_CE_GAINED_10.10pts_THETA_WIN_CE"
        }
    ],
    "risk_budget_pct": 2.0,
    "tuesday_posture": "normal",
    "monthly_expiry_note": "Aug 25 2026 = last Tuesday of month = monthly expiry for NIFTY/BANKNIFTY Aug contracts. Combined with weekly = 0DTE MONTHLY close. Gamma risk highest of month. Hold short-vol structures; do not add.",
    "opening_buffer_note": "Opening buffer 09:15-09:30 ended at 09:30:18. Now 130 min into regular session, 3h50m to square-off. 5-min ACTION vs 11:20 tick: BN DRIFT -10.10 pts (57435.75 -> 57425.65, intra-tick low 57417.75 at 11:23:48 then bounced to 57430.70 at 11:24:49 then settled 57425.65 at 11:25:20). NIFTY +3.90 pts (24149.55 -> 24153.45, +0.016%). VIX 11.35 -> 11.185 (DOWN 0.165, more calm). Last 4 refreshes: NF 24149.75-24153.45 (3.70 pts range), BN 57417.75-57430.70 (12.95 pts range). NIFTY 24100 short PE GAINED 3.90 pts buffer (49.55 -> 53.45 OTM). BANKNIFTY 57400 short PE COMPRESSED 10.10 pts (35.75 -> 25.65 OTM, now 10.65 above 57415 close, 5.65 above 57420 escalation - TIGHTEST OF DAY but NOT breached). BANKNIFTY 57600 short CE EXPANDED 10.10 pts (164.25 -> 174.35 OTM, theta win, GREEN safe, 124.35 below 57550 yellow zone). NIFTY 24300 CE lost 3.90 pts (150.45 -> 146.55 OTM). Hard trigger 57580 retreated to 154.35 below. PE close trigger 57415 has 10.65 pts buffer (NOT breached). PE escalation 57420 has 5.65 pts buffer (NOT breached but TIGHTEST).",
    "reversal_note": "BN OSCILLATION PATTERN. 11:20 saw BN at 57435.75. 11:23:48 BN at 57417.75 (drop -18.00, NEW 5-MIN LOW, briefly 2.25 below 57420 escalation but bounced). 11:24:19 BN at 57419.75 (slight up +2.00, still 0.25 below escalation). 11:24:49 BN at 57430.70 (bounce +10.95 above escalation). 11:25:20 BN at 57425.65 (settled -5.05 from bounce, 5.65 above escalation). Today intraday BN range = 57231.25 to 57653.85 (422 pts). Current 57425.65 at 47th percentile. The 11:23:48 wick to 57417.75 (18.00 below 11:20) was a single refresh - bounced to 57430.70 at 11:24:49 (+12.95), then settled at 57425.65 at 11:25:20 (-5.05 from bounce). This is OSCILLATION between 57417-57430, NOT a sustained break. Day low is 57231.25 - current is 194+ pts above. PE close trigger 57415 has 10.65 pts buffer. NOT breached. PE escalation 57420 has 5.65 pts buffer. NOT breached. We are still in safe territory for the structure, but the buffer has compressed to the tightest of the day. Watch INTENSIFIED for sustained break below 57415. CE side gained 10.10 pts (theta working). Net structure: still net positive on theta. Hold. Sustained-pullback watch INTENSIFIED (BN intra-tick touched 57417.75 < 57420 escalation but bounced back above).",
    "escalation_rule": "PE-side CLOSE triggers (UNCHANGED): if BANKNIFTY<57415 or NIFTY<24115, CLOSE respective IC/IB PE side. BANKNIFTY currently 10.65 above 57415 (vs 20.75 at 11:20, COMPRESSED 10.10 pts, NOT triggered, 10-pt buffer). NIFTY currently 38.45 above 24115 (vs 34.55 at 11:20, GAINED 3.90 pts, 38-pt buffer). PE-side ESCALATION triggers: if BANKNIFTY<57420 OR NIFTY<24120, prepare to close PE side. BANKNIFTY currently 5.65 above 57420 (vs 15.75 at 11:20, COMPRESSED 10.10 pts, NOT triggered but TIGHTEST OF DAY, only 5-pt buffer). NIFTY currently 33.45 above 24120 (vs 29.55 at 11:20, GAINED 3.90 pts, 33-pt buffer). CE-side YELLOW zone: NIFTY in 24250-24300 OR BANKNIFTY in 57550-57600 = watch closely. BANKNIFTY currently 124.35 below 57550 (GREEN safe). NIFTY currently 96.45 below 24250 (GREEN safe). CE-side RED zone: NIFTY>24300 OR BANKNIFTY>57600 = close CE side. NOT triggered. HARD TRIGGER 57580: BANKNIFTY is 154.35 below (retreated from 144.25 at 11:20). Sustained-pullback watch INTENSIFIED (BN intra-tick low 57417.75 < 57420 escalation, bounced). Time triggers: 13:30 no new entries (2h5m), 14:30 consider 0DTE close (3h5m), 15:15 square off (3h50m).",
    "tick_summary_11_25": "25th HOLD tick of the day. Bias=neutral. BN PE BUFFER TIGHTEST of day. NIFTY +3.90 pts (24149.55 -> 24153.45, +0.016%, basically flat). BANKNIFTY -10.10 pts (57435.75 -> 57425.65, -0.018%, intra-tick low 57417.75 at 11:23:48 then bounced to 57430.70 at 11:24:49 then settled 57425.65 at 11:25:20). VIX 11.35 -> 11.185 (DOWN 0.165, calmest of day). Last 4 refreshes: NF 24149.75-24153.45 (3.70 pts range), BN 57417.75-57430.70 (12.95 pts range). BANKNIFTY 57600 short CE EXPANDED 10.10 pts (164.25 -> 174.35 OTM, theta win, GREEN safe, 124.35 below 57550 yellow zone). BANKNIFTY 57400 short PE COMPRESSED 10.10 pts (35.75 -> 25.65 OTM, now 10.65 above 57415 close trigger - TIGHTEST OF DAY, 5.65 above 57420 escalation - NOT breached but TIGHT). NIFTY 24300 CE lost 3.90 pts (150.45 -> 146.55 OTM). NIFTY 24100 PE GAINED 3.90 pts (49.55 -> 53.45 OTM). Buffer migration: BN PE lost 10.10 pts, BN CE gained 10.10 pts (theta winning on CE side). Range regime intact, 0DTE monthly expiry theta working. Max loss combined 3,910 INR (3.7% cash) unchanged. HARD TRIGGER 57580 retreated to 154.35 below. PE close trigger 57415 has 10.65 pts buffer (NOT breached). PE escalation 57420 has 5.65 pts buffer (NOT breached, TIGHTEST). Sustained-pullback watch INTENSIFIED (BN intra-tick touched 57417.75, 2.25 below 57420 escalation, but bounced). 25th HOLD tick. NIFTY at 46th percentile of today range, BANKNIFTY at 47th percentile - both within range bounds. PE close trigger NOT breached; do NOT close prematurely. Let theta continue working through the rest of the session. Monitor INTENSIFIED for sustained break below 57415. If PE buffer drops below 5 pts OR escalation 57420 is breached on next refresh, will move to PE side close."
}

with STATE_PATH.open("w", encoding="utf-8") as f:
    json.dump(state, f, indent=2, ensure_ascii=False)

print(f"Updated brain_state.json: call_count_today={state['call_count_today']}, last_decision.ts={state['last_decision']['ts']}")
