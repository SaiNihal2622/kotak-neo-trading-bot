#!/usr/bin/env python
"""
Update brain_state.json: replace last_decision with the 09:25 IST decision,
prepend the old 09:20 last_decision into history, bump call_count_today.
"""
import json
from pathlib import Path

p = Path(r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json")
state = json.loads(p.read_text(encoding="utf-8-sig"))

# Old last_decision goes into history (compact form to keep history small)
old = state.get("last_decision", {})
history_entry = {
    "ts": old.get("ts"),
    "timestamp": old.get("timestamp"),
    "ist_time": old.get("ist_time"),
    "bias": old.get("bias"),
    "source": old.get("source"),
    "max_positions": old.get("max_positions"),
    "actions": old.get("actions", []),
    "note": old.get("note"),
    "market_session": old.get("market_session"),
    "vix": old.get("vix"),
    "risk_budget_pct": old.get("risk_budget_pct"),
    "bias_decision": old.get("bias_decision"),
    "macro_in_blackout": old.get("macro_in_blackout"),
    "actions_count": old.get("actions_count", 0),
}

# New last_decision (full reasoning, 09:25 IST)
new_decision = {
    "ts": "2026-08-31T03:55:00Z",
    "timestamp": "2026-08-31T03:55:00Z",
    "ist_time": "2026-08-31 09:25:00",
    "bias": "neutral",
    "source": "mavis",
    "max_positions": 0,
    "actions": [],
    "note": "opening_0925_mon_5min_nochange_observation_holds_unchanged_from_09_20_vix_11.0225_calm_1.0x_mult_minus_0.0925_from_09_20_flat_calm_candle_regime_both_range_conf_0.7_NIFTY_5d_range_pct_0.38pct_BNF_0.59pct_tight_pre_market_5d_trend_NIFTY_minus_0.67pct_BNF_minus_0.02pct_flat_unchanged_0_open_positions_clean_slate_capital_109978_realized_9978_bot_alive_process_A_2009364_process_B_1940_at_09_24_30_16_both_livekotak_heartbeats_firing_scan_loop_in_opening_buffer_skip_mode_9_15_9_30_let_price_settle_per_design_macro_no_blackout_no_events_research_unavailable_pdf_download_failing_monday_brief_risk_on_gap_up_posture_normal_max_2pct_preferred_strategies_bull_call_vertical_iron_condor_operational_constraint_opening_session_no_entries_before_09_30_per_15min_buffer_post_open_HOLD_until_09_30_then_reassess_with_opening_15min_candle_settled_preferred_setup_iron_condor_at_09_30_if_range_holds_and_vix_stays_calm",
    "market_session": "opening",
    "vix": 11.0225,
    "risk_budget_pct": 0,
    "bias_decision": "neutral",
    "macro_in_blackout": False,
    "decision_summary": "09:25 IST cron tick (10 min after 09:15, 5 min before opening_end 09:30). Still in 15-min opening buffer 9:15-9:30. VIX 11.0225 (calm, 1.0x mult, -0.0925 from 09:20 - flat calm, well below 12 calm-band threshold). candle_regime both still range conf 0.7 (NIFTY 5d range_pct 0.38% unchanged, BNF 0.59% slight expansion from 0.52% at 09:20 - still tight range as today's pre-market bar develops). 0 open positions unchanged. No macro blackout (macro.upcoming empty). Bot tick_count advancing on both scanner processes (process A 2,009,364 at 09:24:30 + process B 1,940 at 09:25:16, both firing LiveKotak heartbeats every ~30s). Bot scan loop is correctly in opening-buffer skip mode - log lines show '[SCAN] cycle=609/615/621/627/633 | skip: in opening buffer (9:15-9:30 - let price settle)' at 09:23/09:24/09:25. Path bug NOT seen - 30c0fc9 fix still working. No force-action check failed, no brain-action check failed warnings. Both action channels working as designed. NO material state change vs 09:20: only VIX -0.0925 (flat), tick_count advanced (process A +4,368 ticks, process B +226 ticks in 5 min), NIFTY 5d trend -0.58%->-0.67% (live print 24077.85->24055.65, slight drift), BNF 5d trend -0.01%->-0.02% (live print 57518.85->57513.30, essentially flat), BNF range_pct 0.52%->0.59% (slight expansion as today's intraday bar develops, still classified tight). Decision (HOLD/neutral/0 actions) is structurally the same as 09:20 - still in 15-min opening buffer, no entries before 09:30 IST. Defer to 09:30 reassessment with opening 15-min candle settled.",
    "rationale": "09:25 IST cron tick (10 min after 09:15 market-open boundary, 5 min before opening_end 09:30). (a) Market session = 'opening' (15-min post-open buffer 9:15-9:30 per settings.yaml + intraday config). Per operational rule no_new_trades_after 13:30 + avoid_first_5_min_after_open true + 15-min post-open buffer convention, NO new entries before 09:30 IST. Bot main loop scan is in opening-buffer skip mode (log: 'skip: in opening buffer (9:15-9:30 - let price settle)') - this is by design. (b) 0 open positions, clean slate, capital 1,09,978 INR, realized +9,978 INR. (c) VIX 11.0225 (calm band < 12, 1.0x mult, -0.0925 from 09:20 - flat calm). (d) candle_regime both range conf 0.7 (NIFTY 5d range_pct 0.38% unchanged, BNF 0.59% slight expansion from 0.52% - tight range, today's pre-market bar developing). Today's pre-market NIFTY range 24128.70-24038.40 = 90pt (0.37% of open), BNF 57576.25-57238.50 = 338pt (0.59% of open) - both still within tight range profile. (e) 5d trend NIFTY -0.67% (slight down, refreshed from -0.58% at 09:20 - live print drift), BNF -0.02% (essentially flat, refreshed from -0.01%) - neither hits trending regime threshold. (f) No macro events per macro.upcoming (empty list), in_blackout=false, next_event_min=null. (g) Research unavailable - PDF download still failing. Candle+macro+VIX-only mode. (h) Bot alive on both scanner processes: process A tick_count 2,009,364, process B tick_count 1,940. LiveKotak heartbeats firing every ~30s on both. (i) Monday brief unchanged: regime=risk_on, gap_up, posture=normal, max 2.0% risk per trade, preferred_strategies=[bull_call_vertical, iron_condor], skip_first_30min=false (brief internal contradiction: explicit flag=false but rationale recommends skip - defer to operational 15-min buffer which is more conservative). (j) Operational constraint: opening session = no entries before 09:30. Defer to 09:30. (k) Material change vs 09:20: minimal - VIX -0.0925 (flat calm), tick_count advanced, NIFTY 5d trend -0.58%->-0.67% (live print drift 24077.85->24055.65), BNF 5d trend -0.01%->-0.02% (live print drift 57518.85->57513.30), BNF range_pct 0.52%->0.59% (slight expansion as today's intraday bar develops, still classified tight). All changes are within noise band; nothing regime-changing. (l) Once 09:30 hits: if candle_regime stays range, VIX stays <13, no macro event, and opening 15-min candle is unremarkable, then preferred_strategies=iron_condor (range match) is the natural pick. Until then: HOLD, bias=neutral, 0% new risk, 0 actions.",
    "risk_budget_reasoning": "Risk budget = 0% new capital for the Monday 09:25 IST 5-min nochange observation cron tick. (a) OPENING session is the 15-min post-open buffer (09:15-09:30) - bot main loop will not place new orders during opening buffer, only at/after opening_end (09:30). 15-min post-open buffer per settings.yaml + intraday config. (b) VIX 11.0225 < 12 = calm band, 1.0x mult, -0.0925 from 09:20 (still flat calm). (c) Conservative override (VIX>13 OR gap>0.5%) = FALSE - market otherwise eligible. (d) 0 open positions, no existing risk to manage. (e) Monday brief posture=normal = max 2.0% new risk per trade eligible at 09:30+. (f) gap_up signal from brief (US S&P +0.72% Fri) - lean cautious, defer until opening 15-min candle prints. (g) No macro events, no blackout. (h) Research unavailable - no max_pain / PCR / FII flows to bias toward. (i) preferred_strategies=iron_condor (range match), bull_call_vertical (directional). (j) Bot alive and ready. (k) NO change from 09:20 decision. No new capital at risk until 09:30 reassessment. HOLD, bias=neutral, 0% new risk, 0 actions.",
    "candle_regime_evidence": {
        "NIFTY": {
            "confidence": 0.7,
            "regime": "range",
            "reason": "range=0.38% tight + vix=11.0225 low (calm band, 1.0x mult, -0.0925 from 09:20 - flat calm). 5d trend -0.67% per yfinance (slight down, refreshed from -0.58% at 09:20, but within range bounds - not a trending regime signal). Today's pre-market bar 2026-08-31: open 24117.55 high 24128.70 low 24038.40 close 24055.65 (live print drifted from 24077.85 at 09:20) - tight 90pt pre-market range (0.37% of open), continuation of Friday's tight range. 5d candles (2026-08-24 to 2026-08-31): 24219.05, 24334.55, 24207.75, 24090.85, 24055.65 - oscillating within ~279pt range, no directional conviction. Live print at 09:25 (10 min into opening), opening 15-min candle still forming. Range regime intact. Iron condor setup still valid post-09:30. Wait for opening 15-min candle to confirm range vs expansion.",
            "range_pct": 0.38,
            "last_close": 24055.65,
            "trend_5d": "down",
            "change_5d_pct": -0.67
        },
        "BANKNIFTY": {
            "confidence": 0.7,
            "regime": "range",
            "reason": "range=0.59% tight + vix=11.0225 low (calm band, 1.0x mult, -0.0925 from 09:20 - flat calm). 5d trend -0.02% per yfinance (essentially flat, refreshed from -0.01% at 09:20). Today's pre-market bar 2026-08-31: open 57353.75 high 57576.25 low 57238.50 close 57513.30 (live print drifted from 57518.85 at 09:20, high refreshed from 57539.40, range_pct widened from 0.52% to 0.59% as BNF pre-market spread expanded from 301pt to 338pt) - still tight range (0.59% of open), continuation of Friday's tight range. 5d candles (2026-08-24 to 2026-08-31): 57525.95, 57514.20, 57783.75, 57509.95, 57513.30 - oscillating within ~478pt range, no directional conviction. Live print at 09:25 (10 min into opening), opening 15-min candle still forming. Range regime intact. Iron condor setup still valid post-09:30. Wait for opening 15-min candle to confirm range vs expansion.",
            "range_pct": 0.59,
            "last_close": 57513.30,
            "trend_5d": "flat",
            "change_5d_pct": -0.02
        }
    },
    "macro_evidence": {
        "upcoming": [],
        "in_blackout": False,
        "interpretation": "macro.upcoming is an empty list, in_blackout=false, next_event_min=null. QUIET macro calendar for the new week. Monday brief macro_blackout_soon=false, macro_events_next_7d=[]. No RBI policy, Fed, or US CPI in the immediate window. Monthly NIFTY expiry was Friday 15:30 (PASSED, no settlement issues since 0 positions). New weekly series starts today. Macro is QUIET - no event-driven constraint on new entries today. Combined with range regime + calm VIX + monday brief risk_on + posture normal, the macro layer is supportive of iron condor (range) or bull_call_vertical (directional) post-09:30."
    },
    "research_evidence": {
        "available": False,
        "fallback": "Research PDF download still failing (kotak_research.download_latest_research_pdf:52 WARNING at 09:25). Candle+macro+VIX-only mode. No max_pain, PCR, or FII flows available. Defer to: (a) candle_regime both range conf 0.7 - primary signal, (b) VIX 11.0225 calm - volatility favorable for premium-selling, (c) US S&P +0.72% / Nasdaq +1.57% Fri - US tailwind from monday_brief, (d) 0 open positions clean slate, (e) preferred_strategies from brief = [bull_call_vertical, iron_condor]. No research-driven bias override."
    },
    "open_positions_summary": {
        "note": "0 open positions (clean slate since 2026-08-27 EOD square-off). Capital 1,09,978 INR, realized +9,978 INR for the run-to-date. Friday 2026-08-28 EOD was HOLD (0 positions, monthly NIFTY expiry passed clean). Weekend: no new positions. New weekly series starts today. Bot alive (process A tick 2,009,364 + process B tick 1,940 at 09:24:30/25:16, both firing LiveKotak heartbeats). OPENING session - 10 min into 15-min opening buffer (9:15-9:30) per design - bot main loop scan is skipping with message 'skip: in opening buffer (9:15-9:30 - let price settle)'. Operational constraint: no new entries before 09:30. Next meaningful action: 09:30 post-buffer with opening 15-min candle settled, then reassess iron_condor (range match) vs bull_call_vertical (gap_up + risk_on) per preferred_strategies.",
        "details": [],
        "max_reached": False,
        "count": 0,
        "max_positions_limit": 2
    },
    "tick_context": {
        "previous_decision_ist": "2026-08-31 09:20:00",
        "previous_decision_bias": "neutral",
        "previous_decision_actions_count": 0,
        "decision_changed": False,
        "decision_change_reason": "09:25 IST cron tick (5 min after 09:20). NO material state change vs 09:20. VIX -0.0925 (11.115 -> 11.0225, still calm flat). candle_regime both range conf 0.7 (regime unchanged, NIFTY range_pct same 0.38%, BNF range_pct 0.52%->0.59% as today's pre-market bar continues to develop - still classified tight). 5d trend NIFTY -0.58%->-0.67% (slight drift in NIFTY live print 24077.85->24055.65 - pre-market range still tight), BNF -0.01%->-0.02% (essentially flat, BNF live print 57518.85->57513.30 - bouncing back). 0 open positions unchanged. capital 1,09,978 unchanged. bot alive both processes (tick_count advanced: 2,004,996 -> 2,009,364 process A, 1,714 -> 1,940 process B). macro empty (unchanged). research unavailable (unchanged). Monday brief unchanged (risk_on/gap_up/normal/2%/[bull_call_vertical, iron_condor]). Bot scan loop in opening-buffer skip mode - log: '[SCAN] cycle=609/615/621/627/633 | skip: in opening buffer (9:15-9:30 - let price settle)'. Operational constraint: opening session = no entries before 09:30. Decision (HOLD/neutral/0 actions) is structurally the same as 09:20. No Telegram ping (deduped by send_trader_tg.py - same bias, same actions). No chat ping (no material change in decision).",
        "key_change_since_previous": "Tick_count advanced: process A 2,004,996 -> 2,009,364 (+4,368 ticks in 5 min = ~14.6 ticks/sec); process B 1,714 -> 1,940 (+226 ticks in 5 min = ~0.75 ticks/sec). Both heartbeats firing every ~30s. VIX -0.0925 (flat calm). candle_regime unchanged. BNF range_pct slightly expanded 0.52%->0.59% (BNF pre-market high-low spread widened from 301pt to 338pt as today's bar develops - still tight regime). NIFTY live print 24077.85->24055.65 (drift down 22pt). BNF live print 57518.85->57513.30 (drift down 5pt, essentially flat). 5d trend refreshed: NIFTY -0.58%->-0.67%, BNF -0.01%->-0.02% (negligible). Bot scan loop still in opening-buffer skip mode. Decision unchanged. Bias unchanged. Actions unchanged. No Telegram dedup reason: bias + actions identical to 09:20.",
        "monday_brief_summary": {
            "regime_hint": "risk_on",
            "india_open_gap_signal": "gap_up",
            "recommended_posture": "normal",
            "max_risk_per_trade_pct": 2.0,
            "skip_first_30min_per_brief": False,
            "skip_first_30min_per_brief_rationale": "gap_up -> skip 30min (brief internal contradiction: explicit flag=false but rationale recommends skip)",
            "preferred_strategies": ["bull_call_vertical", "iron_condor"],
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
        "log_tail_evidence_bot_alive": "2026-08-31 09:23:01.573 | INFO | __main__:run_paper:1244 | [SCAN] cycle=609 | skip: in opening buffer (9:15-9:30 - let price settle) | 2026-08-31 09:23:03.611 | INFO | __main__:run_paper:1237 | [SCAN] cycle=35371 | skip: in opening buffer (9:15-9:30 - let price settle) | 2026-08-31 09:23:16.118 | INFO | kotak_bot.data.live_feed:_live_kotak_loop:437 | LiveKotak heartbeat: authed=True subscribed=2 latest=2 tick_count=1864 | 2026-08-31 09:23:30.134 | INFO | kotak_bot.data.live_feed:_live_kotak_loop:437 | LiveKotak heartbeat: authed=True subscribed=48 latest=48 tick_count=2008452 | 2026-08-31 09:23:31.581 | INFO | __main__:run_paper:1244 | [SCAN] cycle=615 | skip: in opening buffer (9:15-9:30 - let price settle) | 2026-08-31 09:23:33.621 | INFO | __main__:run_paper:1237 | [SCAN] cycle=35377 | skip: in opening buffer (9:15-9:30 - let price settle) | 2026-08-31 09:24:01.590 | INFO | __main__:run_paper:1244 | [SCAN] cycle=621 | skip: in opening buffer (9:15-9:30 - let price settle) | 2026-08-31 09:24:03.694 | INFO | __main__:run_paper:1237 | [SCAN] cycle=35383 | skip: in opening buffer (9:15-9:30 - let price settle) | 2026-08-31 09:24:16.123 | INFO | kotak_bot.data.live_feed:_live_kotak_loop:437 | LiveKotak heartbeat: authed=True subscribed=2 latest=2 tick_count=1902 | 2026-08-31 09:24:30.174 | INFO | kotak_bot.data.live_feed:_live_kotak_loop:437 | LiveKotak heartbeat: authed=True subscribed=48 latest=48 tick_count=2009364 | 2026-08-31 09:24:31.597 | INFO | __main__:run_paper:1244 | [SCAN] cycle=627 | skip: in opening buffer (9:15-9:30 - let price settle) | 2026-08-31 09:24:33.726 | INFO | __main__:run_paper:1237 | [SCAN] cycle=35389 | skip: in opening buffer (9:15-9:30 - let price settle) | 2026-08-31 09:25:01.607 | INFO | __main__:run_paper:1244 | [SCAN] cycle=633 | skip: in opening buffer (9:15-9:30 - let price settle) | 2026-08-31 09:25:03.791 | INFO | __main__:run_paper:1237 | [SCAN] cycle=35395 | skip: in opening buffer (9:15-9:30 - let price settle) | 2026-08-31 09:25:16.129 | INFO | kotak_bot.data.live_feed:_live_kotak_loop:437 | LiveKotak heartbeat: authed=True subscribed=2 latest=2 tick_count=1940. Both scanner processes alive (process A tick_count 2,009,364 + process B tick_count 1,940 at 09:24:30/25:16), both firing LiveKotak heartbeats every ~30s. Bot scan loop is in opening-buffer skip mode per design - log lines show '[SCAN] skip: in opening buffer (9:15-9:30 - let price settle)' at 09:23:01, 09:23:03, 09:23:31, 09:23:33, 09:24:01, 09:24:03, 09:24:31, 09:24:33, 09:25:01, 09:25:03. No errors in tail. Path bug NOT seen - 30c0fc9 fix still working. No force-action check failed, no brain-action check failed warnings. Both action channels working as designed."
    },
    "actions_count": 0
}

# Mutate state
state["last_decision"] = new_decision
state["timestamp"] = "2026-08-31T03:55:00Z"
state["call_count_today"] = state.get("call_count_today", 0) + 1
state["history"] = [history_entry] + state.get("history", [])

# Write back (utf-8-sig to match existing style)
p.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8-sig")

print(f"OK: last_decision updated to 09:25 IST. call_count_today={state['call_count_today']}. history prepended (now {len(state['history'])} entries).")
