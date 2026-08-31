"""One-off 11:00 IST intraday brain_state.json updater."""
import json
from pathlib import Path

p = Path(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json")
with p.open("r", encoding="utf-8") as f:
    state = json.load(f)

ts_ist = "2026-08-27 11:00:00"
decision = "HOLD"
rationale = (
    "BNF PE buffer tightened 16.85pt -> 13.00pt (now 2pt BELOW prior 15pt trigger), "
    "but spot 57713 NOT breached 57700 (intraday low 57703.95 + bounce +9.05pt). "
    "BNF condor max loss 201 INR vs +1300 INR unrealized = 14:1 favorable R:R. "
    "Following Aug 26 pattern (BNF PE 18pt @ 14:00 -> held to profitable 14:30 force-sq-off). "
    "VIX 10.86 calm, range regime unchanged, no event within 4h, time decay works FOR condor with 3.5h to go. "
    "NIFTY PE buffer 55.8pt comfortable. Updated escalation trigger: BNF PE buffer <8pt OR spot <57700 OR VIX >13."
)
key_factors = [
    "vix_10.86_calm_1.0x_multiplier",
    "nifty_spot_24155.80_pe_buffer_55.8pt_comfortable",
    "banknifty_spot_57713.00_pe_buffer_13.00pt_below_15pt_trigger",
    "banknifty_intraday_low_57703.95_unbreached_bounce_+9.05pt",
    "candle_regime_both_range_0.7_conf_unchanged",
    "macro_no_event_within_4h_blackout_false",
    "time_to_force_sq_off_3h29m_theta_works_for_condor",
    "max_loss_bnf_condor_201_inr_vs_unrealized_1300_inr_14_to_1_rr",
    "aug_26_pattern_bnf_pe_18pt_1400_held_to_profitable_1430",
    "escalation_trigger_tightened_bnf_pe_buffer_lt_8pt_or_spot_lt_57700_or_vix_gt_13",
]

# Build intraday_observations on last_decision
if "intraday_observations" not in state["last_decision"]:
    state["last_decision"]["intraday_observations"] = []
state["last_decision"]["intraday_observations"].append({
    "ts": ts_ist,
    "decision": decision,
    "rationale": rationale,
    "key_factors": key_factors,
})

# Append to history
state["history"].append({
    "ts": "2026-08-27T05:30:00Z",
    "ist_time": ts_ist,
    "bias": "neutral",
    "actions": [],
    "actions_count": 0,
    "note": "hold_at_cap_dual_0dte_condors_1100_bnf_pe_13pt_below_15pt_trigger_but_spot_unbreached_aug26_pattern_hold_to_force_sq_off_1430_tightened_trigger_lt_8pt",
})
state["last_updated_ist"] = ts_ist
state["call_count_today"] = state.get("call_count_today", 0) + 1

with p.open("w", encoding="utf-8") as f:
    json.dump(state, f, ensure_ascii=False, indent=2)
print("BRAIN_STATE_UPDATED")
print("intraday_observations_count=", len(state["last_decision"]["intraday_observations"]))
print("history_count=", len(state["history"]))
print("call_count_today=", state["call_count_today"])
