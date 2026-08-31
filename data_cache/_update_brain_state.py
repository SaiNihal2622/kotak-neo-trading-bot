#!/usr/bin/env python3
"""Update brain_state.json last_decision + history atomically, preserving existing history."""
import json
import sys
from datetime import datetime, timezone, timedelta

PATH = r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json"

new_decision = {
    "ts": "2026-08-31T10:06:20Z",
    "ist_time": "2026-08-31 15:36:20",
    "bias": "cautious",
    "source": "mavis",
    "max_positions": 0,
    "actions": [],
    "note": "market_closed",
    "decision_summary": "15:36:20 IST cron tick (10 min 31s after 15:25:29 last decision). market_session=closed (15:30 IST market close hit 6m ago). 0 open positions, capital Rs.1,09,978, realized +Rs.9,978 preserved. Day session over. No entries possible - market_closed structural state. Per cron spec Step 5, written HOLD with note=market_closed and sent via --summary Telegram. Carry-forward P1 to Tue Sep 1: kotak_prod_feed._fetch_option_quotes:560 HTTP 400 'Please set the Neo symbol max value to 50' - chunk symbols into <=50 batches, then nssm restart KotakBotPaper.",
    "rationale": "15:36:20 IST post-market-close HOLD. market_session=closed (15:30 IST hit 6m ago). 0 open positions, no exposure. 13:30 no_new_trades_after cutoff 2h06m past, 14:30 force-square 1h06m past, 15:15 EOD square-off 21m past (N/A 0 positions), 15:30 market close 6m past. No entries possible. Bot confirmed alive: LiveKotak heartbeat tick_count=1130 at 15:35:08. LiveIndia refresh 15:35:51: NIFTY 24080.40 / BNF 58024.95 / VIX 11.16. VIX still calm 1.0x mult (irrelevant - market closed). Candle regime both range conf 0.7 (5d yfinance), range_pct 0.86/0.87% tight (refreshed 15:36). Macro quiet, in_blackout=false, upcoming=[]. P1 carry-forward to Tue Sep 1: kotak_prod_feed._fetch_option_quotes HTTP 400 batch-size blocker.",
    "risk_budget_reasoning": "Risk budget = 0% new capital at 15:36:20 IST (market_closed - no entries allowed, no positions to manage). (a) market_session=closed (15:30 IST hit 6m ago). (b) 0 open positions. (c) 13:30 no_new_trades_after cutoff 2h06m past. (d) 14:30 force-square 1h06m past - N/A (0 positions). (e) 15:15 EOD square-off 21m past - N/A (0 positions). (f) 15:30 market close 6m past. (g) Capital preserved at Rs.1,09,978, realized +Rs.9,978. (h) HTTP 400 P1 carry-forward: kotak_prod_feed._fetch_option_quotes:560 - chunk symbols into <=50 batches, then nssm restart KotakBotPaper. (i) Tomorrow (Tue Sep 1) thesis: range regime both conf 0.7, VIX 11.16 calm 1.0x mult, macro quiet, preferred_strategies=[bull_call_vertical, iron_condor] from monday_brief, monday posture normal max_risk_per_trade_pct=2.0%. Risk budget Tue 09:30+: up to 2.0% per trade per monday_brief (normal posture).",
    "candle_regime_evidence": {
        "NIFTY": {
            "confidence": 0.7,
            "regime": "range",
            "range_pct": 0.86,
            "last_close": 24090.85,
            "trend_5d": "down",
            "change_5d_pct": -0.66,
            "reason": "range=0.86% tight (5d yfinance, refreshed 15:36) + VIX 11.16 calm 1.0x mult. NIFTY 24090.85 5d last close. 5d candles: 24252.0, 24219.05, 24334.55, 24207.75, 24090.85. adx low. Range-bound, low-vol. Live intraday 15:35: NIFTY 24080.40 (slight RED vs last close -10.45pt, range-bound action). Mavis plan is for NIFTY only, not BANKNIFTY. Market closed - data frozen for analysis purposes only."
        },
        "BANKNIFTY": {
            "confidence": 0.7,
            "regime": "range",
            "range_pct": 0.87,
            "last_close": 57509.95,
            "trend_5d": "flat",
            "change_5d_pct": -0.44,
            "reason": "range=0.87% tight (5d yfinance, refreshed 15:36) + VIX 11.16 calm 1.0x mult. BNF 57509.95 5d last close. 5d candles: 57761.95, 57525.95, 57514.20, 57783.75, 57509.95. Range-bound. Live intraday 15:35: BNF 58024.95 (above last close +514.95pt, well above today's range)."
        }
    },
    "macro_evidence": {
        "upcoming": [],
        "in_blackout": False,
        "interpretation": "macro.upcoming=[], in_blackout=false, next_event_min=null. QUIET macro calendar. No RBI/Fed/CPI in immediate window. Macro layer is QUIET. The decision to HOLD is based on the market being CLOSED (15:30 IST market close hit 6m ago), NOT on macro concerns."
    },
    "research_evidence": {
        "available": False,
        "fallback": "Research PDF download still failing (kotak_research.download_latest_research_pdf:57 WARNING at 15:35 - 'Could not find derivatives PDF URL (kotakneo.com layout drift); using stale cache if present'). Candle+macro+VIX-only mode. No max_pain, PCR, or FII flows available. Defer to: (a) candle_regime both range conf 0.7, (b) VIX 11.16 calm 1.0x mult, (c) US S&P +0.74% / Nasdaq +1.57% Fri - monday_brief catalyst (5d), (d) preferred_strategies from brief = [bull_call_vertical, iron_condor], (e) macro quiet. No research-driven bias override needed. The decision to HOLD is based on the market being CLOSED, not on research-driven bias."
    },
    "open_positions_summary": {
        "count": 0,
        "max_positions_limit": 2,
        "post_trade_count": 0,
        "max_reached": False,
        "details": [],
        "note": "0 open positions at 15:36:20 IST. market_session=closed (15:30 IST hit 6m ago). 13:30 cutoff 2h06m past, 14:30 force-square 1h06m past, 15:15 EOD square-off 21m past (N/A 0 positions), 15:30 market close 6m past. No new entries possible. Capital Rs.1,09,978, realized +Rs.9,978. Day session over."
    },
    "tick_context": {
        "previous_decision_ist": "2026-08-31 15:25:29",
        "previous_decision_bias": "cautious",
        "previous_decision_actions_count": 0,
        "previous_decision_note": "intraday_post_1330_cutoff_closing_session_no_new_entries_terminal_hold",
        "last_actions_note": "market_closed",
        "last_actions_ist": "2026-08-31 15:31:48",
        "decision_changed": True,
        "decision_change_reason": "15:36:20 IST post-market-close tick (10 min 31s after 15:25:29 last_brain, 4 min 32s after 15:31:48 last_actions). market_session=closed (15:30 IST market close hit 6m ago) - structural transition from 'closing_session' to 'closed' state. (a) market_session TRANSITIONED from 'closing' (15:00-15:30 window) at 15:25 -> 'closed' at 15:30 - new structural state, not present in last_brain. (b) Bot confirmed alive: LiveKotak heartbeat tick_count=1130 at 15:35:08. (c) 0 open positions carried over. (d) LiveIndia refresh 15:35:51: NIFTY 24080.40 / BNF 58024.95 / VIX 11.16 (VIX -0.05 vs 11.21 at 15:25, irrelevant - market closed). (e) Candle regime UNCHANGED: both range conf 0.7, range_pct 0.86/0.87% tight (refreshed 15:36 yfinance, similar to 0.56/0.68% at 15:25 - slight refresh difference but same regime call). (f) Bias cautious UNCHANGED. (g) Risk budget 0% terminal (market closed). (h) P1 carry-forward UNCHANGED: HTTP 400 fix is the user-actionable item for Tue Sep 1. Note change: closing_session -> market_closed (transitioned state)."
    },
    "intraday_observations": {
        "ts": "2026-08-31T15:36:20+05:30",
        "open_positions": 0,
        "capital": 109977.95,
        "realized_pnl": 9977.95,
        "decision": "HOLD",
        "rationale_short": "15:36:20 IST post-market-close HOLD. market_session=closed (15:30 IST hit 6m ago). 0 open positions. Day session over. P1 carry-forward: HTTP 400 fix.",
        "time_to_force_square": "0m (15:15 hit, N/A 0 positions)",
        "time_to_market_close": "0m (15:30 hit, market closed)",
        "time_to_no_new_trades_cutoff": "0m (already past)",
        "macro_status": "quiet",
        "vix": 11.16,
        "carry_forward_p1": "kotak_prod_feed._fetch_option_quotes:560 chunk symbols into <=50 batches, then nssm restart KotakBotPaper"
    },
    "actions_count": 0,
    "timestamp": "2026-08-31T10:06:20Z"
}

# Atomic read-modify-write
try:
    with open(PATH, 'r', encoding='utf-8') as f:
        state = json.load(f)
except Exception as e:
    print(f"ERROR reading brain_state.json: {e}", file=sys.stderr)
    sys.exit(1)

# Promote previous last_decision into history (as a slim record, like existing history entries)
prev = state.get("last_decision")
if prev:
    slim = {
        "ts": prev.get("ts"),
        "timestamp": prev.get("ts"),
        "ist_time": prev.get("ist_time"),
        "bias": prev.get("bias"),
        "source": prev.get("source"),
        "max_positions": prev.get("max_positions"),
        "actions": prev.get("actions", []),
        "note": prev.get("note")
    }
    # Avoid duplicate history entry if previous is identical to the head
    history = state.get("history", [])
    if not history or history[0].get("ist_time") != slim.get("ist_time"):
        history.insert(0, slim)
        # Cap history at 100 to avoid runaway growth
        state["history"] = history[:100]

# Update last_decision, timestamp, call_count
state["last_decision"] = new_decision
state["timestamp"] = new_decision["ts"]
state["call_count_today"] = state.get("call_count_today", 0) + 1
state["today_date"] = "2026-08-31"

# Write atomically
tmp_path = PATH + ".tmp"
try:
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    import os
    os.replace(tmp_path, PATH)
    print(f"OK updated brain_state.json. last_decision.ist_time={new_decision['ist_time']}, call_count_today={state['call_count_today']}, history_len={len(state['history'])}")
except Exception as e:
    print(f"ERROR writing brain_state.json: {e}", file=sys.stderr)
    sys.exit(1)
