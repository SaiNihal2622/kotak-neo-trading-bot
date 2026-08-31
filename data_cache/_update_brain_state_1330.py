"""Update brain_state.json with the 13:30 final intraday decision (no position)."""
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot")
BRAIN_STATE = ROOT / "data_cache" / "brain_state.json"
BRAIN_ACTIONS = ROOT / "data_cache" / "brain_actions.json"
INTRADAY_LOG = ROOT / "Logs" / "mavis_intraday.log"

# Load current state
state = json.loads(BRAIN_STATE.read_text(encoding="utf-8"))
actions = json.loads(BRAIN_ACTIONS.read_text(encoding="utf-8"))

# New 13:30 last_decision (final intraday, no position)
new_decision = {
    "ts": "2026-08-31T08:00:00Z",
    "ist_time": "2026-08-31 13:30:00",
    "bias": "cautious",
    "source": "mavis",
    "max_positions": 0,
    "actions": [],
    "note": "intraday_1330_final_no_open_position_day_closed",
    "decision_summary": (
        "13:30 IST FINAL intraday re-evaluation (last Mavis decision of day). 0 open positions. "
        "0 actions. Day closed. (a) Position check: 0 open positions in paper_state.json (verified live at 13:30 IST). "
        "Capital Rs.1,09,978, realized +Rs.9,978. (b) 13:30 cutoff just hit: bot log shows "
        "[SCAN] cycle=38323 / cycle=3567 'skip: intraday mode - no_new_trades_after (13:30) hit' at 13:30:29-30 IST. "
        "No new entries possible for the rest of the day. (c) HTTP 400 batch-size blocker was the dominant story today: "
        "18+ consecutive ticks of '_fetch_option_quotes:560 HTTP 400 Neo symbol max value to 50'. "
        "The 13:30 cutoff closes the door on any last-second fix. "
        "(d) 14:30 force-square-off is N/A (0 positions). 15:30 EOD square-off is N/A. "
        "15:15 EOD report and 15:45 state backup will run as scheduled. "
        "(e) Thesis remains intact for tomorrow (Tue Sep 1) - range regime both conf 0.7, VIX 11.2 calm, "
        "macro quiet, preferred iron_condor. The HTTP 400 fix is the #1 priority item for next session. "
        "(f) Sentiment: disappointing day - 0 fills, full day blocked, but capital preserved at +9,978 INR. "
        "No loss, no exposure. (g) The user-actionable P1 (HTTP 400 batch size fix) is the key carry-forward. "
        "Action: chunk symbols into <=50 batches in kotak_bot/data/kotak_prod_feed.py:_fetch_option_quotes line 560. "
        "nssm restart KotakBotPaper to pick up. (h) Bias cautious UNCHANGED. Risk budget 0% (terminal). Day end."
    ),
    "rationale": (
        "13:30 IST intraday re-eval, last decision of the day. 0 open positions, 0 actions. "
        "Bot log confirms 13:30 cutoff hit (intraday mode no_new_trades_after 13:30). "
        "HTTP 400 batch-size blocker on kotak_prod_feed._fetch_option_quotes:560 made the day a forced HOLD. "
        "Day ends with no positions, no exposure, +9,978 INR paper P&L preserved. "
        "Carry-forward P1: chunk symbols into <=50 batches, nssm restart, ready for Tue Sep 1."
    ),
    "risk_budget_reasoning": (
        "Risk budget = 0% new capital at 13:30 IST (terminal for the day). "
        "(a) 0 open positions. (b) 13:30 cutoff hit - no new entries possible. "
        "(c) HTTP 400 blocker structurally prevented all entries today. "
        "(d) Capital preserved at Rs.1,09,978, realized +Rs.9,978. "
        "(e) No action required today; tomorrow's thesis (range regime, VIX calm, iron_condor preferred) is intact."
    ),
    "candle_regime_evidence": {
        "NIFTY": {
            "confidence": 0.7,
            "regime": "range",
            "range_pct": 0.86,
            "last_close": 24090.85,
            "trend_5d": "down",
            "change_5d_pct": -0.66,
            "reason": "range=0.86% tight (5d yfinance) + VIX 11.2 calm. NIFTY 24066.85 at 13:30, holding above 24065. Day closed."
        },
        "BANKNIFTY": {
            "confidence": 0.7,
            "regime": "range",
            "range_pct": 0.87,
            "last_close": 57509.95,
            "trend_5d": "flat",
            "change_5d_pct": -0.44,
            "reason": "range=0.87% tight (5d yfinance) + VIX 11.2 calm. BNF 57391.70 at 13:30, above 57300. Day closed."
        }
    },
    "macro_evidence": {
        "upcoming": [],
        "in_blackout": False,
        "interpretation": "Macro layer quiet. No RBI/Fed/CPI in immediate window. No event-driven constraint."
    },
    "open_positions_summary": {
        "count": 0,
        "max_positions_limit": 2,
        "post_trade_count": 0,
        "max_reached": False,
        "details": [],
        "note": "0 open positions at 13:30. 13:30 cutoff hit. Day closed. Capital Rs.1,09,978, realized +Rs.9,978."
    },
    "tick_context": {
        "previous_decision_ist": "2026-08-31 13:25:00",
        "previous_decision_bias": "cautious",
        "previous_decision_actions_count": 0,
        "decision_changed": False,
        "decision_change_reason": (
            "13:30 IST FINAL intraday re-eval. Decision structurally identical to 13:25 (HOLD, 0 actions) but with explicit "
            "day-close. No open position, 13:30 cutoff hit, no new entries possible. Day ends with no exposure, "
            "+9,978 INR paper P&L preserved. HTTP 400 P1 carry-forward to tomorrow."
        ),
    },
    "intraday_observations": {
        "ts": "2026-08-31T13:30:00+05:30",
        "open_positions": 0,
        "capital": 109977.95,
        "realized_pnl": 9977.95,
        "decision": "HOLD",
        "rationale_short": "0 open positions, 13:30 cutoff hit, no new entries possible. Day closed. HTTP 400 P1 carry-forward.",
        "time_to_force_square": "N/A (0 positions)",
        "time_to_market_close": "2h00m",
        "macro_status": "quiet",
        "vix": 11.19,
        "carry_forward_p1": "kotak_prod_feed._fetch_option_quotes:560 chunk symbols into <=50 batches, then nssm restart KotakBotPaper"
    },
    "actions_count": 0,
    "timestamp": "2026-08-31T08:00:00Z"
}

# Update state
state["last_decision"] = new_decision
state["timestamp"] = "2026-08-31T08:00:00Z"
state["call_count_today"] = state.get("call_count_today", 0) + 1

# Prepend a short history entry (keep file size manageable)
history_entry = {
    "ts": "2026-08-31T08:00:00Z",
    "ist_time": "2026-08-31 13:30:00",
    "bias": "cautious",
    "source": "mavis",
    "max_positions": 0,
    "actions": [],
    "note": "intraday_1330_final_no_open_position_day_closed"
}
history = state.get("history", [])
history.insert(0, history_entry)
# Cap history to last 30 entries to keep file size in check
state["history"] = history[:30]

# Write back
BRAIN_STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"brain_state.json updated. last_decision.ist_time = {new_decision['ist_time']}, call_count_today = {state['call_count_today']}, history_len = {len(state['history'])}")

# Append to mavis_intraday.log
INTRADAY_LOG.parent.mkdir(parents=True, exist_ok=True)
with INTRADAY_LOG.open("a", encoding="utf-8") as f:
    f.write(f"2026-08-31 13:30:00+05:30 | intraday_1330_final | decision=HOLD | pnl=+Rs.9,978 | positions=0 | "
            f"rationale=no_open_position_13:30_cutoff_hit_HTTP400_P1_carry_forward\n")
print("mavis_intraday.log appended")
