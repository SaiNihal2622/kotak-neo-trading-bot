"""In-place update of brain_state.json: replace last_decision only, preserve history.
Run: python _update_brain_state_15_16.py
"""
import json
from pathlib import Path

p = Path(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json")
data = json.loads(p.read_text(encoding="utf-8"))

new_last_decision = {
    "ts": "2026-08-31T09:46:00Z",
    "ist_time": "2026-08-31 15:16:00",
    "bias": "cautious",
    "source": "mavis",
    "max_positions": 0,
    "actions": [],
    "note": "intraday_post_1330_cutoff_closing_session_no_new_entries_terminal_hold",
    "decision_summary": "15:16:00 IST cron tick (4 min after 15:12 last tick, 1h46m past 13:30 no_new_trades_after cutoff, 46m past 14:30 force-square, 1m past 15:15 EOD square-off N/A, 14m to 15:30 market close, 29m to 15:45 state backup). CLOSING SESSION (15:00-15:30 IST window). HOLD, 0 actions, bias UNCHANGED cautious. 28th CONSECUTIVE TICK of structural post-cutoff HOLD. (a) Position check: 0 open positions in paper_state.json (verified live via trader_state). Capital Rs.1,09,978, realized +Rs.9,978 preserved. (b) market_session=closing (15:00-15:30). 13:30 no_new_trades_after cutoff is 1h46m past - structural no-entry state. Bot log tail 15:13:49 -> 15:15:50: bot alive, scanning every 2-3s, all cycles (109, 115, 121, 127, 133, 139) reporting skip: intraday mode - no_new_trades_after (13:30) hit. No new entries possible. (c) HTTP 400 batch-size blocker (kotak_prod_feed._fetch_option_quotes:560 Neo symbol max value to 50) remains P1 carry-forward to Tue Sep 1 (irrelevant for this session - entry path closed by 13:30 cutoff AND 14:30 force-square AND 15:15 EOD square-off). Bot alive with LiveKotak heartbeat tick_count=378 at 15:15:08. (d) VIX 11.30 calm 1.0x mult (was 11.26 at 15:12, +0.04, irrelevant). (e) Candles refreshed 15:15: NIFTY last_close 24050.25 (yfinance today bar, -11.50 from 24061.75 at 15:12), range_pct 0.56% tight UNCHANGED, BNF last_close 57397.35 (-16 from 57413.25 at 15:12), range_pct 0.68% tight UNCHANGED. Both range conf 0.7 UNCHANGED. Live spot 15:15:38: NIFTY 24050.25 / BNF 57397.35 / VIX 11.28 (LiveIndia refresh). (f) Time-budget: 1m past 15:15 EOD square-off (N/A, 0 positions), 14m to 15:30 market close, 29m to 15:45 state backup. (g) Bias cautious UNCHANGED. Risk budget 0% (terminal - no entries allowed, no positions to manage). (h) Thesis remains intact for Tue Sep 1: range regime both conf 0.7, VIX ~11.3 calm 1.0x mult, macro quiet, preferred_strategies=[bull_call_vertical, iron_condor] from monday_brief, monday posture normal max_risk_per_trade 2.0%. (i) 28th consecutive tick of post-cutoff HOLD; no change in decision state.",
    "rationale": "15:16:00 IST post-cutoff closing-session HOLD. 0 open positions, 13:30 no_new_trades_after cutoff is 1h46m past, 14:30 force-square is 46m past, 15:15 EOD square-off is 1m past (N/A 0 positions), market_session=closing (15:00-15:30). No new entries possible. Day state: 0 positions, 0 exposure, +9,978 INR paper P&L preserved. Carry-forward P1 to Tue Sep 1: chunk symbols to <=50 in kotak_prod_feed._fetch_option_quotes, then nssm restart KotakBotPaper.",
    "risk_budget_reasoning": "Risk budget = 0% new capital at 15:16:00 IST (terminal - no entries allowed, no positions to manage). (a) 0 open positions. (b) 13:30 no_new_trades_after cutoff is 1h46m past - structural no-entry state. (c) 14:30 force-square is 46m past - N/A (0 positions). (d) 15:15 EOD square-off is 1m past - N/A (0 positions). (e) Capital preserved at Rs.1,09,978, realized +Rs.9,978. (f) HTTP 400 P1 carry-forward: kotak_prod_feed._fetch_option_quotes:560 - chunk symbols into <=50 batches, then nssm restart KotakBotPaper. (g) Tomorrow (Tue Sep 1) thesis: range regime both conf 0.7, VIX 11.30 calm 1.0x mult, macro quiet, preferred_strategies=[bull_call_vertical, iron_condor] from monday_brief. Risk budget Tue 09:30+: up to 2.0% per trade per monday_brief (normal posture).",
    "candle_regime_evidence": {
        "NIFTY": {
            "confidence": 0.7,
            "regime": "range",
            "range_pct": 0.56,
            "last_close": 24050.25,
            "trend_5d": "down",
            "change_5d_pct": -0.7,
            "reason": "range=0.56% tight (5d yfinance, refreshed 15:15) + VIX 11.30 calm 1.0x mult. NIFTY 24050.25 5d last close (yfinance, today bar updated to close 24050.25 from 24061.75 at 15:12). 5d candles: 24219.05, 24334.55, 24207.75, 24090.85, 24050.25. Today bar 2026-08-31: open 24117.55 high 24128.70 low 23993.60 close 24050.25. Range-bound, low-vol. adx low."
        },
        "BANKNIFTY": {
            "confidence": 0.7,
            "regime": "range",
            "range_pct": 0.68,
            "last_close": 57397.35,
            "trend_5d": "flat",
            "change_5d_pct": -0.22,
            "reason": "range=0.68% tight (5d yfinance, refreshed 15:15) + VIX 11.30 calm 1.0x mult. BNF 57397.35 5d last close (today bar updated to close 57397.35 from 57413.25 at 15:12). 5d candles: 57525.95, 57514.20, 57783.75, 57509.95, 57397.35. Today bar: open 57353.75 high 57576.25 low 57187.35 close 57397.35. Range-bound. Mavis plan is for NIFTY only, not BANKNIFTY."
        }
    },
    "macro_evidence": {
        "upcoming": [],
        "in_blackout": False,
        "interpretation": "macro.upcoming=[], in_blackout=false, next_event_min=null. QUIET macro calendar. No RBI/Fed/CPI in immediate window. Macro layer is QUIET - no event-driven constraint. The decision to HOLD is based on the intraday 13:30 no_new_trades_after cutoff being past AND market_session=closing (15:00-15:30), NOT on macro concerns."
    },
    "research_evidence": {
        "available": False,
        "fallback": "Research PDF download still failing (kotak_research.download_latest_research_pdf:52 WARNING at 15:15). Candle+macro+VIX-only mode. No max_pain, PCR, or FII flows available. Defer to: (a) candle_regime both range conf 0.7, (b) VIX 11.30 calm 1.0x mult, (c) US S&P +0.74% / Nasdaq +1.57% Fri - monday_brief catalyst (5d), (d) preferred_strategies from brief = [bull_call_vertical, iron_condor], (e) macro quiet. No research-driven bias override needed. The decision to HOLD is based on the 13:30 no_new_trades_after cutoff AND market_session=closing, not on research-driven bias."
    },
    "open_positions_summary": {
        "count": 0,
        "max_positions_limit": 2,
        "post_trade_count": 0,
        "max_reached": False,
        "details": [],
        "note": "0 open positions at 15:16:00 IST. 13:30 cutoff hit 1h46m ago, 14:30 force-square hit 46m ago, 15:15 EOD square-off hit 1m ago (N/A, 0 positions), market_session=closing. No new entries possible. Capital Rs.1,09,978, realized +Rs.9,978. N/A for entry - terminal state."
    },
    "tick_context": {
        "previous_decision_ist": "2026-08-31 15:12:18",
        "previous_decision_bias": "cautious",
        "previous_decision_actions_count": 0,
        "previous_decision_note": "intraday_post_1330_cutoff_closing_session_no_new_entries_terminal_hold",
        "decision_changed": False,
        "decision_change_reason": "15:16:00 IST post-cutoff closing-session tick (4 min after 15:12 last tick, 1h46m past 13:30 no_new_trades_after cutoff, 46m past 14:30 force-square, 1m past 15:15 EOD square-off N/A, 14m to 15:30 market close, 29m to 15:45 state backup). Structural decision (HOLD, 0 actions, bias cautious) UNCHANGED. 28th CONSECUTIVE TICK of structural post-cutoff HOLD. (a) Bot confirmed alive: LiveKotak heartbeat tick_count=378 at 15:15:08. (b) 0 open positions carried over (paper_state.json unchanged). (c) Candle refresh 15:12->15:15: VIX 11.26 -> 11.30 (+0.04, irrelevant), today bar updated (NIFTY 24061.75 -> 24050.25 / BNF 57413.25 -> 57397.35 - close moved 11-16pt down, range_pct unchanged 0.56% / 0.68%). (d) HTTP 400 P1 carry-forward unchanged (chunk symbols, then nssm restart). (e) Live spot 15:15:38: NIFTY 24050.25 / BNF 57397.35 / VIX 11.28. (f) Risk budget 0% terminal. (g) Time-budget: 1m past 15:15 EOD square-off (N/A, 0 positions), 14m to 15:30 market close, 29m to 15:45 state backup. (h) Carry-forward to Tue Sep 1: HTTP 400 fix is the user-actionable item."
    },
    "intraday_observations": {
        "ts": "2026-08-31T15:16:00+05:30",
        "open_positions": 0,
        "capital": 109977.95,
        "realized_pnl": 9977.95,
        "decision": "HOLD",
        "rationale_short": "15:16:00 IST post-cutoff closing-session HOLD. 0 open positions. 13:30 cutoff 1h46m past, 14:30 force-square 46m past, 15:15 EOD 1m past (N/A 0 positions), market_session=closing. No new entries possible. HTTP 400 P1 carry-forward.",
        "time_to_force_square": "0m (15:15 hit, N/A 0 positions)",
        "time_to_market_close": "14m (15:30)",
        "time_to_no_new_trades_cutoff": "0m (already past)",
        "macro_status": "quiet",
        "vix": 11.30,
        "carry_forward_p1": "kotak_prod_feed._fetch_option_quotes:560 chunk symbols into <=50 batches, then nssm restart KotakBotPaper"
    },
    "actions_count": 0,
    "timestamp": "2026-08-31T09:46:00Z"
}

# Replace only the top-level "last_decision" key. Keep "history" intact.
data["last_decision"] = new_last_decision
# also bump today_date / timestamp for the file-level metadata
data["timestamp"] = "2026-08-31T09:46:00Z"
data["today_date"] = "2026-08-31"
data["call_count_today"] = data.get("call_count_today", 0) + 1

p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"OK: brain_state.json updated, last_decision={data['last_decision']['ist_time']}, history entries={len(data.get('history', []))}, call_count_today={data['call_count_today']}")
