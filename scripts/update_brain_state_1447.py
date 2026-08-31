"""Update brain_state.json with tick @ 14:47 IST.

Preserves all existing structure (history, decisions arrays, executor_status, etc.)
and only swaps last_decision + bumps call_count_today.
"""
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

STATE_PATH = Path(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json")

IST = timezone(timedelta(hours=5, minutes=30))
now_ist = datetime.now(IST)
ts_utc = now_ist.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
ist_str = now_ist.strftime("%Y-%m-%d %H:%M:%S")

with STATE_PATH.open("r", encoding="utf-8") as f:
    state = json.load(f)

old_count = state.get("call_count_today", 0)
new_count = old_count + 1

new_decision = {
    "ts": ts_utc,
    "ist_time": ist_str,
    "bias": "cautious",
    "source": "mavis",
    "max_positions": 0,
    "actions": [],
    "note": "no_setup_post_force_square_post_no_new_trades_after_28min_to_1515_square_off",
    "reasoning": (
        f"Tick at {ist_str} IST on Tue 2026-08-25 [0DTE MONTHLY expiry day - INTRADAY SQUARE-OFF WINDOW]. "
        f"77 min after 13:30 entry cutoff, 407 min into regular session, 17 min post force-square mark, "
        f"28 min to 15:15 square-off final bell, 43 min to 15:30 market close. "
        f"NO STATE CHANGE vs prior ticks (66->67): open_positions still EMPTY, cash 100229 INR, "
        f"realized_pnl 229 INR (small positive day +0.23%). "
        f"Live NIFTY ~24210 (last 24210.50, range 24115-24216 today, drifting mid-range). "
        f"Live BN ~57414 (last 57414.35, range 57231-57653 today, both directions absorbing). "
        f"VIX 11.14 (calm, <12, range regime confirmed). "
        f"Range regime both underlyings [NIFTY conf=0.7 range=0.42%, BANKNIFTY conf=0.7 range=0.74%]. "
        f"Macro: no events, no blackout. Research: still unavailable (54+ ticks). "
        f"Bot log tail shows normal cycle skipping at +5s tick (cycle 10546->10582 in last ~3min, ~12/min sustained). "
        f"No new executor activity. DECISION: HOLD ALL [67th tick of day, call_count_today={new_count}]. "
        f"No positions to manage. No new entries (post 13:30 cutoff). Strategy exhausted for the day. "
        f"NEXT TICK TRIGGERS: (1) Periodic 5-min silent ticks till 15:15 EOD. "
        f"(2) EOD at 15:15 - market close. (3) Manual review of day PnL. "
        f"(4) Prepare for tomorrow Wed 2026-08-26 (no expiry, weekly)."
    ),
    "candle_regime_evidence": {
        "NIFTY": {
            "regime": "range",
            "confidence": 0.7,
            "reason": "range=0.42% tight + vix=11.1 low",
            "5d_change_pct": 0.55,
            "range_pct": 0.42,
            "today_move_pts": -10.6,
        },
        "BANKNIFTY": {
            "regime": "range",
            "confidence": 0.7,
            "reason": "range=0.74% tight + vix=11.1 low",
            "5d_change_pct": 0.31,
            "range_pct": 0.74,
            "today_move_pts": 25.2,
        },
    },
    "macro_evidence": {
        "in_blackout": False,
        "next_event": None,
        "events_next_7d": [],
    },
    "research_evidence": {
        "available": False,
        "note": "research not available [Kotak PDF download failed, 54th consecutive tick], skipped research bias",
    },
    "monday_brief_evidence": {
        "applicable": False,
        "note": "Tuesday - Monday brief not consulted",
    },
    "position_evidence": [],
    "executor_status": {
        "standalone_executor": "dead_3d_no_orders_since_2026-08-22",
        "in_process_resilient": "ACTIVE_no_new_activity_post_force_square",
        "force_square_backstop": "FIRED_14:30:03_2026-08-25_all_2_ICs_closed",
        "working_exit": "force_square_completed",
    },
    "tick_summary_14_47": (
        f"67th tick of day, STILL ALL POSITIONS CLOSED. Bias=cautious. "
        f"NO CHANGE vs 14:40: open_positions still EMPTY. cash 100229 INR, realized_pnl 229 INR "
        f"(small positive day +0.23% on 100k). Live NIFTY ~24210, BN ~57414 "
        f"(both held mid-range, low-vol drift, no event trigger). VIX 11.14 (calm, <12, range regime). "
        f"Cycle 10546->10582 (+36 in ~3min, ~12/min sustained). "
        f"REASON FOR HOLD: (1) No positions to manage. (2) Post 13:30 cutoff = no new entries. "
        f"(3) 28 min to 15:15 square-off final bell. (4) Strategy day EXHAUSTED. "
        f"NEXT TRIGGERS: (a) 5-min periodic silent ticks till 15:15 EOD. "
        f"(b) EOD 15:15 - market close. (c) Manual review of day PnL. "
        f"(d) Prep for tomorrow Wed 2026-08-26 (no expiry)."
    ),
    "timestamp": ts_utc,
    "confidence": 0.95,
    "risk_budget_pct": 0.0,
    "rationale": (
        f"HOLD ALL - Same as 14:40: force-square fired 14:30:03-04, all 2 ICs closed. "
        f"open_positions still empty. Post 13:30 cutoff, no new entries. Day strategy exhausted. "
        f"Day PnL +229 INR. 28 min to 15:15 EOD. Silent monitoring."
    ),
}

state["call_count_today"] = new_count
state["last_decision"] = new_decision

# Append to decisions[] (newest-first list, so insert at index 0)
if "decisions" not in state or not isinstance(state["decisions"], list):
    state["decisions"] = []
state["decisions"].insert(0, {
    "ist_time": ist_str,
    "bias": "cautious",
    "note": "no_setup_post_force_square_post_no_new_trades_after_28min_to_1515_square_off",
    "actions": [],
})

with STATE_PATH.open("w", encoding="utf-8") as f:
    json.dump(state, f, indent=2, ensure_ascii=False)

print(f"OK: brain_state.json updated. call_count_today: {old_count} -> {new_count}. last_decision ist_time={ist_str}")
