"""One-tick brain decision writer for 12:08 IST, 2026-08-26."""
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

IST = timezone(timedelta(hours=5, minutes=30))
now_ist = datetime.now(IST)
ts_utc = now_ist.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
ist_str = now_ist.strftime("%Y-%m-%d %H:%M:%S")

# Compose the decision
last_decision = {
    "ts": ts_utc,
    "ist_time": ist_str,
    "bias": "neutral",
    "source": "mavis",
    "max_positions": 2,
    "actions": [],
    "note": "at_cap_dual_0dte_condors_managed_no_new_entries",
    "market_session": "regular",
    "vix": 10.78,
    "cash": 106693.5,
    "open_positions_count": 2,
    "open_positions_legs": 8,
    "macro_in_blackout": False,
    "research_available": False,
    "next_event_minutes_away": 3082,
    "candle_regime_evidence": {
        "NIFTY": {
            "regime": "range",
            "confidence": 0.7,
            "last_close": 24275.7,
            "trend_5d": "flat",
            "change_5d_pct": 0.18,
            "range_pct": 0.45,
            "reason": "range=0.45% tight + vix=10.8 low",
        },
        "BANKNIFTY": {
            "regime": "range",
            "confidence": 0.7,
            "last_close": 57877.3,
            "trend_5d": "up",
            "change_5d_pct": 0.66,
            "range_pct": 0.66,
            "reason": "range=0.66% tight + vix=10.8 low",
        },
    },
    "macro_evidence": {
        "in_blackout": False,
        "upcoming_events": [
            {
                "name": "monthly_expiry_NIFTY",
                "datetime_ist": "2026-08-28 15:30",
                "importance": 2,
                "minutes_away": 3082,
            }
        ],
        "interpretation": "No near-term event risk. Next event Fri 15:30 NIFTY monthly expiry (~51h away). 0DTE theta accelerating — both condors expire TODAY at 15:30, ~3.4h of theta burn remaining. Wed weekly expiry on BANKNIFTY also TODAY. No blackout.",
    },
    "research_evidence": {
        "available": False,
        "fallback": "PDF download still failing. Candle+macro only. NIFTY 5d +0.18% flat, range 0.45% (very tight). BANKNIFTY 5d +0.66% up, range 0.66% (tight). VIX 10.78 calm (still <12 calm regime). Range + low VIX supports holding dual-condor premium-selling structure through expiry. No directional edge to add.",
    },
    "open_positions_summary": {
        "NIFTY_condor_0DTE": {
            "expiry": "2026-08-26",
            "legs": 4,
            "structure": "short 24450 CE / long 24550 CE + short 24250 PE / long 24150 PE",
            "net_credit_estimate": 58.94,
            "qty_units": 65,
            "credit_inr": 3831,
            "max_loss_inr": 5358,
            "rationale": "Spot ~24275.7 (yfinance partial close, +1pt from 12:07 at 24274). Short 24250 PE cushion = 26pts (vs 24pt at 12:07, 71pt at 10:36 — spot drifted closer to short PE then stabilized). Short 24450 CE cushion = 174pts (very safe). Theta accelerating, ~3.4h to expiry. Long 24150 PE still 126pt OTM — strong protection. No adjustment; force_square_off at 14:30 covers tail risk.",
        },
        "BANKNIFTY_condor_0DTE": {
            "expiry": "2026-08-26",
            "legs": 4,
            "structure": "short 58100 CE / long 58200 CE + short 57900 PE / long 57800 PE",
            "net_credit_estimate": 90.23,
            "qty_units": 30,
            "credit_inr": 2707,
            "max_loss_inr_remaining": 3000,
            "rationale": "Spot ~57877.3 (yfinance partial close, +1pt from 12:07 at 57876). Short 57900 PE 23pt ITM (stable vs 12:07). Short 58100 CE 223pt cushion (very safe). PE spread 100pt-wide (57800-57900) caps PE-side max loss at 3000 INR. Long 57800 PE 77pt ITM (provides protection if spot drops further — would need 78pt more drop to fully breach the wing). ~3.4h to expiry. force_square_off at 14:30 is automatic safety net. Holding to expiry gives theta time to decay the far-OTM CE side while PE side remains defined-risk at 100pt width. Asymmetric payoff still favors holding; force_square_off at 14:30 covers tail risk.",
        },
    },
    "bias_decision": "neutral",
    "risk_budget_pct": 3.0,
    "risk_budget_reasoning": "Range regime + VIX 10.78 (<12 calm) = full 1.0x sizing on merits. But 2 condors already live (8 legs) = at position cap. No room for new entries. 3% cap reflects no-new-entries state, not a sizing downgrade. Combined worst-case max loss if both wings fully breached at expiry = 5358 + 3000 = 8358 INR (~7.8% of cash) — well within risk tolerance. VIX 10.78 still calm. Bias=neutral, at position cap 2/2 — no new entries. Theta burn over remaining 3.4h will continue eroding short-option value. force_square_off at 14:30 covers tail risk. No adjustment warranted.",
    "planned_setup": None,
    "decision_summary": "HOLD (regular session 12:08 IST, 2h23m into session). Both 0DTE condors live and decaying. Spots basically flat vs 12:07: NIFTY 24275.7 (+1pt, 26pt OTM from short 24250 PE), BANKNIFTY 57877.3 (+1pt, 23pt ITM below short 57900 PE). Both condors still within long-wing protection: NIFTY long 24150 PE 126pt OTM, BANKNIFTY long 57800 PE 77pt ITM. Combined worst-case condor max loss = 8358 INR (~7.8% of cash) — acceptable. VIX 10.78 (calm, <12). Bias=neutral, at position cap 2/2 — no new entries. ~3.4h of theta burn to 15:30 expiry. force_square_off at 14:30 automatic safety net. Decision unchanged from 12:07 and 10:36 — same HOLD, no actions. Telegram dedupe will suppress this tick's message.",
}

# Write brain_actions.json
actions_path = Path(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_actions.json")
actions_path.write_text(json.dumps(last_decision, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"OK: brain_actions.json written. ist_time={ist_str}")

# Update brain_state.json
state_path = Path(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json")
with state_path.open("rb") as f:
    raw = f.read()
# Strip UTF-8 BOM if present
if raw.startswith(b"\xef\xbb\xbf"):
    raw = raw[3:]
state = json.loads(raw.decode("utf-8"))

state["call_count_today"] = state.get("call_count_today", 0) + 1
state["last_decision"] = last_decision

# Append to history (cap at 20 entries)
hist_entry = {
    "ts": ts_utc,
    "ist_time": ist_str,
    "bias": "neutral",
    "actions": [],
    "note": "at_cap_dual_0dte_condors_managed_no_new_entries",
}
history = state.get("history", [])
history.insert(0, hist_entry)
state["history"] = history[:20]
state["last_updated_ist"] = ist_str

state_path.write_text(
    json.dumps(state, indent=2, ensure_ascii=False),
    encoding="utf-8",
)
print(f"OK: brain_state.json updated. call_count_today={state['call_count_today']} history_len={len(state['history'])}")
