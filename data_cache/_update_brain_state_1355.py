"""One-shot update for brain_state.json: 13:50 last_decision → 13:55."""
import json
from pathlib import Path

STATE_PATH = Path(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json")

with STATE_PATH.open(encoding="utf-8") as f:
    state = json.load(f)

# 1) Push the current last_decision (the 13:50 one) to history as a slim entry
slim_keys = ("ts", "ist_time", "bias", "source", "max_positions", "actions", "note")
old_last = state["last_decision"]
slim_entry = {k: old_last[k] for k in slim_keys if k in old_last}
state.setdefault("history", [])
state["history"].insert(0, slim_entry)

# 2) Build the new 13:55 last_decision (terminal-hold, same shape as 13:50)
new_last = {
    "ts": "2026-08-31T08:25:00Z",
    "ist_time": "2026-08-31 13:55:00",
    "bias": "cautious",
    "source": "mavis",
    "max_positions": 0,
    "actions": [],
    "note": "intraday_post_1330_cutoff_no_new_entries_terminal_hold",
    "decision_summary": (
        "13:55 IST cron tick (5 min after 13:50 terminal-hold tick, 25 min past 13:30 no_new_trades_after "
        "cutoff). HOLD, 0 actions, bias UNCHANGED cautious. 19th CONSECUTIVE TICK of structural post-cutoff HOLD. "
        "(a) Position check: 0 open positions in paper_state.json (verified live 13:55 via trader_state). "
        "Capital Rs.1,09,978, realized +Rs.9,978 preserved. (b) 13:30 no_new_trades_after cutoff is now 25 min "
        "past - bot log 13:55:00 IST confirms [SCAN] cycle=38617 + cycle=3861 both 'skip: intraday mode - "
        "no_new_trades_after (13:30) hit'. No new entries possible for the rest of the day. (c) HTTP 400 "
        "batch-size blocker (kotak_prod_feed._fetch_option_quotes:560 'Neo symbol max value to 50') STILL "
        "firing every 2-3 sec in bot log tail 13:55:00 to 13:55:25 (10+ warnings in 25s window) - "
        "irrelevant for this session (entry path closed by 13:30 cutoff) but remains P1 carry-forward to "
        "Tue Sep 1. (d) LiveKotak heartbeat 13:55:19: authed=True subscribed=48 latest=48 tick_count=190728 "
        "(UP from 186938 at 13:50 by +3,790 ticks in 5 min = ~758 ticks/min, normal pace). (e) Spot drift "
        "13:50 -> 13:55 (yfinance 1d close): NIFTY 24062.80 -> 24053.15 -9.65pt (slight RED, still mid-range "
        "23993.60-24128.70), BNF 57393.90 -> 57350.50 -43.40pt (RED, gap from brief close 57509.95 WIDENED "
        "from -116.05pt to -159.45pt). (f) Time-budget: 35m to 14:30 force-square (N/A, 0 positions), "
        "1h35m to 15:30 market close, 20m to 15:15 EOD report, 50m to 15:45 state backup. (g) DUAL MAVIS "
        "ANOMALY PERSISTS: cycle=38617 + cycle=3861 in 13:55:01 bot log (UP from cycle=38563 + cycle=3807 "
        "at 13:50 by +54 each, normal delta). Both scans fire 'skip: intraday mode - no_new_trades_after' "
        "identically. Orphan bot process pattern from AGENTS.md known-issues register. (h) Bias cautious "
        "UNCHANGED. Risk budget 0% (terminal - no entries allowed, no positions to manage). (i) Thesis "
        "remains intact for Tue Sep 1: range regime both conf 0.7, NIFTY range_pct 0.56% / BNF 0.68% "
        "(tight, 5d yfinance), VIX 11.17 calm 1.0x mult, macro quiet, preferred_strategies="
        "[bull_call_vertical, iron_condor] from monday_brief, monday posture normal max_risk_per_trade 2.0%."
    ),
    "rationale": (
        "13:55 IST post-cutoff HOLD. 0 open positions, 13:30 no_new_trades_after cutoff is 25 min past. "
        "Bot log confirms [SCAN] skip: 'intraday mode - no_new_trades_after (13:30) hit'. No new entries "
        "possible. HTTP 400 batch-size blocker on kotak_prod_feed._fetch_option_quotes:560 still firing "
        "(perpetual P1, not actionable this session). Day state: 0 positions, 0 exposure, +9,978 INR paper "
        "P&L preserved. Carry-forward P1 to Tue Sep 1: chunk symbols to <=50 in _fetch_option_quotes, "
        "nssm restart KotakBotPaper."
    ),
    "risk_budget_reasoning": (
        "Risk budget = 0% new capital at 13:55 IST (terminal - no entries allowed, no positions to manage). "
        "(a) 0 open positions. (b) 13:30 no_new_trades_after cutoff is 25 min past - structural no-entry "
        "state. (c) 14:30 force-square is N/A (0 positions). (d) Capital preserved at Rs.1,09,978, realized "
        "+Rs.9,978. (e) HTTP 400 P1 carry-forward: kotak_prod_feed._fetch_option_quotes:560 - chunk symbols "
        "into <=50 batches, then nssm restart KotakBotPaper. (f) Tomorrow (Tue Sep 1) thesis: range regime "
        "both conf 0.7, NIFTY range_pct 0.56% / BNF 0.68% (tight 5d), VIX 11.17 calm 1.0x mult, macro "
        "quiet, preferred_strategies=[bull_call_vertical, iron_condor] from monday_brief. Risk budget Tue "
        "09:30+: up to 2.0% per trade per monday_brief (normal posture)."
    ),
    "candle_regime_evidence": {
        "NIFTY": {
            "confidence": 0.7,
            "regime": "range",
            "range_pct": 0.56,
            "last_close": 24053.15,
            "trend_5d": "down",
            "change_5d_pct": -0.68,
            "reason": (
                "range=0.56% tight (5d yfinance, refreshed 13:55) + VIX 11.17 calm 1.0x mult. NIFTY 24053.15 "
                "close (today intraday bar 2026-08-31: open 24117.55 high 24128.70 low 23993.60 close 24053.15). "
                "adx low. Range-bound, low-vol. Today drift: -37.70pt from brief close 24090.85. "
                "5d candles: 24219.05, 24334.55, 24207.75, 24090.85, 24053.15."
            ),
        },
        "BANKNIFTY": {
            "confidence": 0.7,
            "regime": "range",
            "range_pct": 0.68,
            "last_close": 57350.5,
            "trend_5d": "flat",
            "change_5d_pct": -0.30,
            "reason": (
                "range=0.68% tight (5d yfinance, refreshed 13:55) + VIX 11.17 calm 1.0x mult. BNF 57350.50 "
                "close (today intraday bar: open 57353.75 high 57576.25 low 57187.35 close 57350.50). "
                "Range-bound. Today drift: -159.45pt from brief close 57509.95 (WIDENED from -116.05pt at "
                "13:50 by -43.40pt). 5d candles: 57525.95, 57514.20, 57783.75, 57509.95, 57350.50."
            ),
        },
    },
    "macro_evidence": {
        "upcoming": [],
        "in_blackout": False,
        "interpretation": (
            "macro.upcoming=[], in_blackout=false, next_event_min=null. QUIET macro calendar. No RBI/Fed/CPI "
            "in immediate window. Macro layer is QUIET - no event-driven constraint. The decision to HOLD is "
            "based on the intraday 13:30 no_new_trades_after cutoff being past, NOT on macro concerns."
        ),
    },
    "research_evidence": {
        "available": False,
        "fallback": (
            "Research PDF download still failing (kotak_research.download_latest_research_pdf:52 WARNING at "
            "13:55). Candle+macro+VIX-only mode. No max_pain, PCR, or FII flows available. Defer to: "
            "(a) candle_regime both range conf 0.7, (b) VIX 11.17 calm 1.0x mult, (c) US S&P +0.74% / "
            "Nasdaq +1.57% Fri - monday_brief catalyst (5d), (d) preferred_strategies from brief = "
            "[bull_call_vertical, iron_condor], (e) macro quiet. No research-driven bias override needed. "
            "The decision to HOLD is based on the 13:30 no_new_trades_after cutoff, not on research-driven bias."
        ),
    },
    "open_positions_summary": {
        "count": 0,
        "max_positions_limit": 2,
        "post_trade_count": 0,
        "max_reached": False,
        "details": [],
        "note": (
            "0 open positions at 13:55. 13:30 cutoff hit 25 min ago. No new entries possible. Capital "
            "Rs.1,09,978, realized +Rs.9,978. Spot drift 13:50 -> 13:55: NIFTY -9.65pt slight RED (24053.15 "
            "vs 24062.80, mid-range 23993.60-24128.70), BNF -43.40pt RED (57350.50 vs 57393.90, gap from "
            "brief close WIDENED from -116.05pt to -159.45pt). N/A for entry - past 13:30 cutoff."
        ),
    },
    "tick_context": {
        "previous_decision_ist": "2026-08-31 13:50:00",
        "previous_decision_bias": "cautious",
        "previous_decision_actions_count": 0,
        "previous_decision_note": "intraday_post_1330_cutoff_no_new_entries_terminal_hold",
        "decision_changed": False,
        "decision_change_reason": (
            "13:55 IST post-cutoff tick (5 min after 13:50 terminal-hold tick, 25 min past 13:30 "
            "no_new_trades_after cutoff). Structural decision (HOLD, 0 actions, bias cautious) UNCHANGED from "
            "13:50 + 13:45 + 13:40 + 13:30 + 13:20 + 13:15 + 13:10 + 13:05 + 13:00 + 12:55 + 12:50 + 12:45 + "
            "12:40 + 12:35 + 12:30 + 12:25 + 12:20 + 12:15 + 12:10 + 12:00 + 11:50. 19th CONSECUTIVE TICK of "
            "structural post-cutoff/structural-blocker HOLD. (a) Telegram will dedupe (bias same, actions same, "
            "note same shape) - this is correct because the situation is structurally unchanged. (b) 0 open "
            "positions. (c) Spot drift 13:50->13:55: NIFTY -9.65pt slight RED (24053.15 vs 24062.80 at 13:50, "
            "still mid-range 23993.60-24128.70), BNF -43.40pt RED (57350.50 vs 57393.90 at 13:50, gap from "
            "brief close WIDENED from -116.05pt to -159.45pt) - no actionable signal since already past entry "
            "window. (d) HTTP 400 P1 carry-forward unchanged. (e) DUAL MAVIS ANOMALY persists (cycle=38617 + "
            "cycle=3861, UP from cycle=38563 + cycle=3807 at 13:50 by +54 each, normal delta). (f) Risk "
            "budget 0% terminal. (g) Carry-forward to Tue Sep 1: HTTP 400 fix is the user-actionable item."
        ),
    },
    "intraday_observations": {
        "ts": "2026-08-31T13:55:00+05:30",
        "open_positions": 0,
        "capital": 109977.95,
        "realized_pnl": 9977.95,
        "decision": "HOLD",
        "rationale_short": "13:55 IST post-cutoff HOLD. 0 open positions. 13:30 cutoff 25 min past. No new entries possible. HTTP 400 P1 carry-forward.",
        "time_to_force_square": "35m (N/A, 0 positions)",
        "time_to_market_close": "1h35m",
        "time_to_no_new_trades_cutoff": "0m (already past)",
        "macro_status": "quiet",
        "vix": 11.17,
        "carry_forward_p1": "kotak_prod_feed._fetch_option_quotes:560 chunk symbols into <=50 batches, then nssm restart KotakBotPaper",
    },
    "actions_count": 0,
    "timestamp": "2026-08-31T08:25:00Z",
}
state["last_decision"] = new_last

# 3) Truncate history to last 25 entries to keep file size sane
state["history"] = state["history"][:25]

# 4) Persist
with STATE_PATH.open("w", encoding="utf-8") as f:
    json.dump(state, f, indent=2, ensure_ascii=False)

print("OK: last_decision → 13:55, history[0] = 13:50 slim, len(history) =", len(state["history"]))
