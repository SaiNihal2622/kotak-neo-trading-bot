"""Update brain_state.json with the 09:05 IST trader-desk decision.
Archives the previous last_decision into history, then replaces it.
"""
import json
import os
from datetime import datetime, timezone, timedelta

BS_PATH = r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json"

with open(BS_PATH, "r", encoding="utf-8") as f:
    bs = json.load(f)

# Snapshot the old last_decision
old_decision = bs.get("last_decision", {})

# New last_decision
new_decision = {
    "ts": "2026-08-31T03:35:00Z",
    "timestamp": "2026-08-31T03:35:00Z",
    "ist_time": "2026-08-31 09:05:00",
    "bias": "neutral",
    "source": "mavis",
    "max_positions": 0,
    "actions": [],
    "note": "pre_open_0905_mon_5min_nochange_observation_holds_unchanged_from_09_01_vix_11.07_calm_1.0x_mult_candle_regime_both_range_conf_0.7_nifty_5d_range_0.86pct_bnf_0.87pct_tight_5d_trend_nifty_minus_0.66pct_bnf_minus_0.44pct_unchanged_0_open_positions_clean_slate_capital_109978_realized_9978_bot_alive_process_A_1993044_process_B_1186_at_09_05_29_15_both_livekotak_heartbeats_firing_macro_no_blackout_no_events_research_unavailable_pdf_download_failing_monday_brief_risk_on_gap_up_posture_normal_max_2pct_skip_first_30min_false_per_brief_rationale_says_gap_up_skip_30min_operational_constraint_pre_open_session_no_entries_before_09_30_per_15min_buffer_post_open_HOLD_until_09_30_then_reassess_with_opening_range_settled_preferred_strategies_bull_call_vertical_iron_condor_match_regime",
    "market_session": "pre_open",
    "vix": 11.07,
    "risk_budget_pct": 0,
    "bias_decision": "neutral",
    "macro_in_blackout": False,
    "decision_summary": "09:05 IST 5-min nochange observation tick (4 min after 09:01 pre_open decision). VIX 11.07 (calm, 1.0x mult, +0.0 from 09:01 - flat). candle_regime both still range conf 0.7 (NIFTY 5d range_pct 0.86%, BNF 0.87% per yfinance - tight range). 0 open positions unchanged. No macro blackout (macro.upcoming empty). Bot tick_count advancing on both scanner processes (process A 1,993,044 at 09:05:29 + process B 1,186 at 09:05:15, both firing LiveKotak heartbeats every ~30s). Bot log tail CLEAN: pure heartbeats, no errors. Path bug NOT seen - 30c0fc9 fix still working. No force-action check failed, no brain-action check failed warnings. Both action channels working as designed. NO material state change in 5-min window. Decision (HOLD/neutral/0 actions) is structurally the same as 09:01. Operational constraint unchanged: pre_open session = no entries before 09:30. Monday brief unchanged: risk_on/gap_up/normal posture/2% cap/[bull_call_vertical, iron_condor]/skip_first_30min false. Next meaningful action: 09:15 market open (transition pre_open -> opening), then 09:30 post-buffer with opening 5-min candle settled. Reassess iron_condor (range match) vs bull_call_vertical (gap_up + risk_on directional) at 09:30.",
    "rationale": "09:05 IST 5-min nochange observation tick - same call as 09:01. (a) Market still in pre_open (09:00-09:15 per settings.yaml) - 10 min before pre_open_end, 25 min before opening_end (09:30). Per operational rule no_new_trades_after 13:30 + avoid_first_5_min_after_open true + 15-min post-open buffer convention, NO new entries before 09:30 IST. (b) 0 open positions, clean slate, capital 1,09,978 INR, realized +9,978 INR. (c) VIX 11.07 (calm, 1.0x mult, +0.0 from 09:01 - flat calm). (d) candle_regime both range conf 0.7 (NIFTY 5d range_pct 0.86%, BNF 0.87% per yfinance - tight range, textbook iron condor day). (e) 5d trend NIFTY -0.66% (slight down), BNF -0.44% (flat). (f) No macro events per macro.upcoming (empty list), in_blackout=false, next_event_min=null. (g) Research unavailable - PDF download still failing. Candle+macro+VIX-only mode. (h) Bot alive on both scanner processes: process A tick_count 1,993,044, process B tick_count 1,186. LiveKotak heartbeats firing every ~30s on both. (i) Monday brief unchanged: regime=risk_on, gap_up, posture=normal, max 2.0% risk per trade, preferred_strategies=[bull_call_vertical, iron_condor], skip_first_30min=false (brief internal contradiction). (j) Operational constraint: pre_open session = no entries. Defer to 09:30. (k) NO new state change since 09:01 - same inputs, same output. (l) Once 09:30 hits: if candle_regime stays range, VIX stays <13, no macro event, and opening 5-min candle is unremarkable, then preferred_strategies=iron_condor (range match) is the natural pick. Until then: HOLD, bias=neutral, 0% new risk, 0 actions.",
    "risk_budget_reasoning": "Risk budget = 0% new capital for the Monday 09:05 IST 5-min nochange observation cron tick. (a) PRE_OPEN session is pre-decision - bot main loop will not place new orders during pre_open, only at/after opening_end (09:30). 15-min post-open buffer per settings.yaml + intraday config. (b) VIX 11.07 < 12 = calm band, 1.0x mult, flat vs 09:01. (c) Conservative override (VIX>13 OR gap>0.5%) = FALSE - market otherwise eligible. (d) 0 open positions, no existing risk to manage. (e) Monday brief posture=normal = max 2.0% new risk per trade eligible at 09:30+. (f) gap_up signal from brief (US S&P +0.72% Fri) - lean cautious, defer until opening 5-min candle prints. (g) No macro events, no blackout. (h) Research unavailable - no max_pain / PCR / FII flows to bias toward. (i) preferred_strategies=iron_condor (range match), bull_call_vertical (directional). (j) Bot alive and ready. (k) NO change from 09:01 decision. No new capital at risk until 09:30 reassessment. HOLD, bias=neutral, 0% new risk, 0 actions.",
    "candle_regime_evidence": {
        "NIFTY": {
            "confidence": 0.7,
            "regime": "range",
            "reason": "range=0.86% tight + vix=11.07 low (calm band, 1.0x mult, +0.0 from 09:01 - flat). 5d trend -0.66% per yfinance (slight down, but within range bounds - not a trending regime signal). 5d candles (2026-08-21 to 2026-08-27): 24252.0, 24219.05, 24334.55, 24207.75, 24090.85 - oscillating within ~244pt range, no directional conviction. Live print TBD at 09:15 open. Range regime intact. Iron condor setup still valid post-09:30. Wait for opening 5-min candle to confirm range vs expansion.",
            "range_pct": 0.86,
            "last_close": 24090.85,
            "trend_5d": "down",
            "change_5d_pct": -0.66
        },
        "BANKNIFTY": {
            "confidence": 0.7,
            "regime": "range",
            "reason": "range=0.87% tight + vix=11.07 low (calm band, 1.0x mult, +0.0 from 09:01 - flat). 5d trend -0.44% per yfinance (essentially flat). 5d candles (2026-08-21 to 2026-08-27): 57761.95, 57525.95, 57514.20, 57783.75, 57509.95 - oscillating within ~510pt range, no directional conviction. Live print TBD at 09:15 open. Range regime intact. Iron condor setup still valid post-09:30. Wait for opening 5-min candle to confirm range vs expansion.",
            "range_pct": 0.87,
            "last_close": 57509.95,
            "trend_5d": "flat",
            "change_5d_pct": -0.44
        }
    },
    "macro_evidence": {
        "upcoming": [],
        "in_blackout": False,
        "interpretation": "macro.upcoming is an empty list, in_blackout=false, next_event_min=null. QUIET macro calendar for the new week. Monday brief macro_blackout_soon=false, macro_events_next_7d=[]. India GDP release that was 1594min away on Friday 14:55 (Sun 17:30 IST) has PASSED. No RBI policy, Fed, or US CPI in the immediate window. Monthly NIFTY expiry was Friday 15:30 (PASSED, no settlement issues since 0 positions). New weekly series starts today. Macro is QUIET - no event-driven constraint on new entries today. Combined with range regime + calm VIX + monday brief risk_on + posture normal, the macro layer is supportive of iron condor (range) or bull_call_vertical (directional) post-09:30."
    },
    "research_evidence": {
        "available": False,
        "fallback": "Research PDF download still failing (kotak_research.download_latest_research_pdf:52 WARNING at 09:05). Candle+macro+VIX-only mode. No max_pain, PCR, or FII flows available. Defer to: (a) candle_regime both range conf 0.7 - primary signal, (b) VIX 11.07 calm - volatility favorable for premium-selling, (c) US S&P +0.72% / Nasdaq +1.57% Fri - US tailwind from monday_brief, (d) 0 open positions clean slate, (e) preferred_strategies from brief = [bull_call_vertical, iron_condor]. No research-driven bias override."
    },
    "open_positions_summary": {
        "note": "0 open positions (clean slate since 2026-08-27 EOD square-off). Capital 1,09,978 INR, realized +9,978 INR for the run-to-date. Friday 2026-08-28 EOD was HOLD (0 positions, monthly NIFTY expiry passed clean). Weekend: no new positions. New weekly series starts today. Bot alive (process A tick 1,993,044 + process B tick 1,186 at 09:05:29/15, both firing LiveKotak heartbeats). Pre_open session - 10 min before pre_open_end (09:15), 25 min before opening_end (09:30). Operational constraint: no new entries before 09:30. Next meaningful action: 09:15 market open (session transition), then 09:30 post-buffer with opening 5-min candle settled, then reassess iron_condor (range match) vs bull_call_vertical (gap_up + risk_on) per preferred_strategies.",
        "details": [],
        "max_reached": False,
        "count": 0,
        "max_positions_limit": 2
    },
    "tick_context": {
        "previous_decision_ist": "2026-08-31 09:01:00",
        "previous_decision_bias": "neutral",
        "previous_decision_actions_count": 0,
        "decision_changed": False,
        "decision_change_reason": "09:05 IST 5-min nochange observation cron tick (4 min after 09:01). NO material state change in 5-min window. All inputs identical: VIX 11.07 (flat), candle_regime both range conf 0.7 (unchanged), 5d trend -0.66%/-0.44% (unchanged), 0 open positions (unchanged), capital 1,09,978 (unchanged), bot alive both processes (tick_count advanced as expected: 1,989,012 -> 1,993,044 process A, 996 -> 1,186 process B), macro empty (unchanged), research unavailable (unchanged), Monday brief unchanged (risk_on/gap_up/normal/2%/[bull_call_vertical, iron_condor]). Operational constraint unchanged: pre_open session = no entries before 09:30. Decision (HOLD/neutral/0 actions) is structurally the same as 09:01. No Telegram ping (deduped by send_trader_tg.py). No chat ping (no material change).",
        "key_change_since_previous": "Tick_count advanced: process A 1,989,012 -> 1,993,044 (+4,032 ticks in 4 min = ~16.8 ticks/sec); process B 996 -> 1,186 (+190 ticks in 4 min = ~0.79 ticks/sec). Both heartbeats firing every ~30s. No other material state change. Decision unchanged. Bias unchanged. Actions unchanged.",
        "monday_brief_summary": {
            "regime_hint": "risk_on",
            "india_open_gap_signal": "gap_up",
            "recommended_posture": "normal",
            "max_risk_per_trade_pct": 2.0,
            "skip_first_30min_per_brief": False,
            "skip_first_30min_per_brief_rationale": "gap_up -> skip 30min (brief internal contradiction: explicit flag=false but rationale recommends skip)",
            "preferred_strategies": [
                "bull_call_vertical",
                "iron_condor"
            ],
            "key_catalysts": [
                "S&P +0.72% Friday - US tailwind for Monday Asia open",
                "Nasdaq +1.57% Friday - tech rally spillover",
                "India VIX 11.1 - calm, premium-selling favorable"
            ],
            "key_risks": [
                "Bullion/geopolitics (US jobs data, Iran tensions)",
                "Mcap drop of 7 top firms (Bharti Airtel, RIL)"
            ],
            "next_session_open_ist": "2026-08-31T09:15:00",
            "brief_as_of": "2026-08-30T21:01:10+05:30"
        },
        "log_tail_evidence_bot_alive": "2026-08-31 09:01:15.944 | INFO | LiveKotak heartbeat: authed=True subscribed=2 latest=2 tick_count=1034 | 2026-08-31 09:01:29.352 | INFO | LiveKotak heartbeat: tick_count=1989780 | 2026-08-31 09:02:15.949 | INFO | LiveKotak heartbeat: tick_count=1072 | 2026-08-31 09:02:29.409 | INFO | LiveKotak heartbeat: tick_count=1990639 | 2026-08-31 09:03:15.954 | INFO | LiveKotak heartbeat: tick_count=1110 | 2026-08-31 09:03:29.438 | INFO | LiveKotak heartbeat: tick_count=1991508 | 2026-08-31 09:04:15.958 | INFO | LiveKotak heartbeat: tick_count=1148 | 2026-08-31 09:04:29.475 | INFO | LiveKotak heartbeat: tick_count=1992276 | 2026-08-31 09:05:15.971 | INFO | LiveKotak heartbeat: tick_count=1186 | 2026-08-31 09:05:29.516 | INFO | LiveKotak heartbeat: tick_count=1993044. Both scanner processes alive, both firing LiveKotak heartbeats every ~30s. No errors in tail. Path bug NOT seen - 30c0fc9 fix still working. Both action channels working as designed."
    },
    "actions_count": 0
}

# Update last_decision
bs["last_decision"] = new_decision

# Append old to history
history = bs.get("history", [])
history.append(old_decision)
bs["history"] = history

# Increment today counter
bs["call_count_today"] = bs.get("call_count_today", 0) + 1
bs["timestamp"] = "2026-08-31T03:35:00Z"
bs["today_date"] = "2026-08-31"

# Write back
with open(BS_PATH, "w", encoding="utf-8") as f:
    json.dump(bs, f, ensure_ascii=False, indent=2)

print(f"brain_state.json updated: last_decision={new_decision['ist_time']} bias={new_decision['bias']} actions={len(new_decision['actions'])} history_len={len(history)} call_count_today={bs['call_count_today']}")
