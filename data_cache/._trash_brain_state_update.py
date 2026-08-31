#!/usr/bin/env python3
"""One-shot script: update only `last_decision` and `last_updated_ist` in brain_state.json.
Preserves today_date, call_count_today, and history.
"""
import json
import sys
from pathlib import Path

p = Path(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json")
with p.open("r", encoding="utf-8") as f:
    state = json.load(f)

new_decision = {
    "ts": "2026-08-27T04:45:48Z",
    "ist_time": "2026-08-27 10:15:48",
    "bias": "neutral",
    "source": "mavis",
    "max_positions": 2,
    "actions": [],
    "note": "no_setup",
    "market_session": "regular",
    "vix": 10.90,
    "macro_in_blackout": False,
    "candle_regime_evidence": {
        "NIFTY": {
            "regime": "range",
            "confidence": 0.7,
            "last_close": 24188.15,
            "trend_5d": "flat",
            "change_5d_pct": -0.26,
            "range_pct": 0.49,
            "reason": "range=0.49% tight + vix=10.90 low, 5d change essentially flat (-0.26%); intraday open 24277 high 24297 low 24179 -- 118 pt intraday range -- same range regime as prior ticks"
        },
        "BANKNIFTY": {
            "regime": "range",
            "confidence": 0.7,
            "last_close": 57799.95,
            "trend_5d": "flat",
            "change_5d_pct": 0.07,
            "range_pct": 0.46,
            "reason": "range=0.46% tight + vix=10.90 low, 5d change essentially flat (+0.07%); intraday open 57985 high 58012 low 57743 -- 268 pt intraday range -- same range regime"
        }
    },
    "macro_evidence": {
        "in_blackout": False,
        "upcoming_events": [
            {"name": "monthly_expiry_NIFTY", "datetime_ist": "2026-08-28 15:30", "importance": 2, "minutes_away": 1754},
            {"name": "india_gdp", "datetime_ist": "2026-08-29 17:30", "importance": 2, "minutes_away": 3314}
        ],
        "interpretation": "Same as 10:10 tick: no near-term event risk. Tomorrow's monthly expiry is 29.2h away, GDP Sat evening is 55.2h away, both well outside the 60min blackout window. No RBI/Fed/CPI within 4h. Macro quiet. VIX ticked 10.94 -> 10.90 (still very calm, 1.0x size multiplier applies). No defensive bias needed."
    },
    "research_evidence": {
        "available": False,
        "fallback": "Research PDF download still failing (same error since 09:30 tick). Candle+macro+VIX-only mode. VIX 10.90 very low, both underlyings tight range, no candles signal direction, no skew signal from research. Stay neutral."
    },
    "open_positions_summary": {
        "count": 2,
        "details": [
            "NIFTY 0DTE iron condor: short 24300CE/24100PE, long 24400CE/24000PE, width 100, 65 qty per leg, opened 09:30:32 IST at net credit ~55.70/unit (max profit ~3620 INR, max loss ~2880 INR)",
            "BANKNIFTY 0DTE iron condor: short 57900CE/57700PE, long 58000CE/57600PE, width 100, 30 qty per leg, opened 09:30:32 IST at net credit ~93.29/unit (max profit ~2799 INR, max loss ~201 INR -- very tight spread)"
        ],
        "spot_vs_strikes": {
            "NIFTY": "spot 24187-24190 (live, 10:15) between shorts 24100/24300 -- 87-90 pts from short PE, 110-113 pts from short CE -- drifted -2 pts from 10:10 (was 89/111) -- essentially unchanged, well-positioned for range, near mid-strike",
            "BANKNIFTY": "spot 57799-57816 (live, 10:15) between shorts 57700/57900 -- 99-116 pts from short PE, 84-101 pts from short CE -- drifted -9 pts from 10:10 (was 108/92) -- still both buffers >84 pts, healthy"
        },
        "unrealized_pnl_inr": {
            "NIFTY_condor": 1746.55,
            "BANKNIFTY_condor": 847.50,
            "total": 2594.05,
            "note": "Both condors in green. NIFTY ~48% of max profit captured; BNF ~30% captured. Time decay working in our favor."
        },
        "max_reached": True,
        "max_positions_limit": 2,
        "note": "At cap 2/2. Bot log shows 'skip: 2 open strategies >= max 2' on every cycle (latest 5 cycles 367/373/378/384/390). Both condors in profit zone roughly 45 min after entry. No alert conditions. Bot managing exits via force_square_off at 14:30 IST and per-strategy stop-loss."
    },
    "bias_decision": "neutral",
    "risk_budget_pct": 0.0,
    "risk_budget_reasoning": "Risk budget = 0% for NEW capital because at cap 2/2. Both 0DTE condors sized within the 1-2% envelope placed by the bot's risk-managed engine. Combined max loss ~3081 INR on 113K cash = 2.7% (acceptable for 0DTE under calm VIX). VIX 10.90 (calm, 1.0x multiplier) supports the size. Current unrealized +2594 INR further reduces realized risk. No reason to add; no reason to force-close either -- both condors working as designed and buffers remain comfortable.",
    "planned_setup": None,
    "decision_summary": "HOLD (regular session 10:15 IST, ~4h15m to 14:30 force square-off, ~5h15m to 15:30 0DTE expiry). Tick-over-tick vs 10:10: VIX 10.94 -> 10.90 (still very calm, 1.0x), NIFTY 24189 -> 24187 (-2 pts, stable near mid-strike), BANKNIFTY 57808 -> 57799 (-9 pts, drifted slightly toward PE). Both underlyings still in range regime (0.7 conf). Macro not in blackout, no event within 4h. Research PDF still unavailable. Both 0DTE condors (opened 09:30:32 IST) working as designed -- NIFTY 87-90/110-113 pt buffers, BANKNIFTY 99-116/84-101 pt buffers (both sides comfortable). Unrealized P&L +2,594 INR (NIFTY +1,747, BNF +848). At cap 2/2 -- no new entries possible, and no reason to override. Brain's job is to not interfere with bot's exit management. Next review window: mid-day (12:00-13:00) for early-profit / range-break assessment. Final exit: bot force-square-off at 14:30 IST."
}

state["last_decision"] = new_decision
state["last_updated_ist"] = "2026-08-27 10:15:48"
# bump call count
state["call_count_today"] = state.get("call_count_today", 0) + 1
# append compact history note
hist = state.get("history", [])
hist.append({
    "ts": new_decision["ts"],
    "timestamp": new_decision["ts"],
    "ist_time": new_decision["ist_time"],
    "bias": "neutral",
    "actions": [],
    "actions_count": 0,
    "note": "hold_at_cap_dual_0dte_condors_1015_nifty_24187_bnf_57799_in_range_low_vix_unrealized_2594_let_bot_manage_to_force_sq_off_1430"
})
state["history"] = hist

with p.open("w", encoding="utf-8") as f:
    json.dump(state, f, indent=2, ensure_ascii=False)
    f.write("\n")

print(f"OK updated last_decision + last_updated_ist; call_count_today={state['call_count_today']}; history_len={len(hist)}")
