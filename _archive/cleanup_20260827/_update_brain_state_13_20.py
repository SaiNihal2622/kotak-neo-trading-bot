"""Update brain_state.json with 13:20 last_decision. Preserves history."""
import json
import os

p = r"C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json"
with open(p, "r", encoding="utf-8") as f:
    s = json.load(f)

new_dec = {
  "ts": "2026-08-25T07:50:08Z",
  "ist_time": "2026-08-25 13:20:08",
  "bias": "cautious",
  "source": "mavis",
  "max_positions": 2,
  "actions": [
    {
      "id": "act-13-20-001",
      "type": "CLOSE",
      "strategy": "BANKNIFTY_IRON_CONDOR_PE_SIDE",
      "underlying": "BANKNIFTY",
      "expiry": "2026-08-25",
      "legs": [
        {"side": "BUY", "strike": 57400, "option_type": "PE", "qty": 30, "price": None},
        {"side": "SELL", "strike": 57300, "option_type": "PE", "qty": 30, "price": None}
      ],
      "rationale": "HARD TRIGGER STILL MET \u2014 BN<57350 sustained 9+ consecutive refreshes since 13:11. 57300 WING BREACHED 3RD TIME at 13:20 [57293.40 = 6.60 below wing]. Brief bounce to 57345 at 13:17:06 [+47 pts in 1 min] suggested recovery but BN re-tested and broke wing again within 3 minutes. Short 57400 PE now ~106.6 pts ITM [vs 102.5 at 13:15, deepened 4.1 pts]. Spread at ~58% of max loss. CE side 57600 still ~307 OTM, only PE side at risk. EXECUTOR DEAD 3d \u2014 re-emitting for rule-based correctness + audit trail + in case executor wakes. Force-square at 14:30 [1h10m] is the working backstop. 10 min to 13:30 no-new-entries cutoff. NIFTY 24127.80 = 27.80 OTM from 24100 PE, 12.80 pts above 24115 hard trigger [TIGHT but safe, holding NIFTY IB unchanged].",
      "ttl_sec": 60
    }
  ],
  "note": "hard_trigger_still_met_BN_below_57350_9plus_consecutive_readings_57300_wing_breached_3rd_time_13_20_PE_side_57400_short_now_106.6_ITM_spread_58pct_max_loss_re_emit_CLOSE_PE_side_executor_dead_3d_force_square_14_30_backstop_CE_side_307_OTM_safe_NIFTY_24127.80_12.80pts_above_24115_hard_trigger_still_safe",
  "reasoning": "Tick at 13:20 IST on Tue 2026-08-25 [0DTE MONTHLY expiry day]. 5 min after 13:15 tick, 260 min into regular session [past 09:30 opening buffer], 1h55m to 15:15 square-off, 10 min to 13:30 no-new-entries cutoff, 1h10m to 14:30 force-square. Market in regular session. VIX 11.30 [calm, <12]. Range regime confirmed for both underlyings [NIFTY conf=0.7 range=0.34%, BANKNIFTY conf=0.7 range=0.74%]. Macro: no events next 7d, no blackout. Research: still unavailable [38th consecutive tick]. Live positions: 2 strategies [NIFTY IB + BANKNIFTY IC] at max_positions=2. KEY STATE vs 13:15 tick: BN made a brief bounce attempt [13:17:06 57345.20 = +47.7 pts from 13:15 close of 57297.50] but FAILED to hold above 57300, settling back into 57300-57306 range, then DROPPING again to 57293.40 at 13:20. This bounce-and-fall pattern is GAMMA-ACCELERATED 0DTE behavior \u2014 the brief recovery was a stop-hunt / short-covering, then the real move resumed down. 57300 wing now breached for the 3rd time in 10 minutes [13:14 57294.85, 13:15 57297.50, 13:20 57293.40]. NIFTY 13:15-13:20: 24128.00, 24134.35, 24133.30, 24133.50, 24129.60, 24131.45, 24129.40, 24127.80 [7pt range 24127-24134, softened 0.20pts from 13:15 but stable]. PE SIDE OF BN IC: short 57400 PE now 106.6 pts ITM [vs 102.5 at 13:15, deepened 4.1 pts]. 57300 wing 6.6 pts BELOW [BREACHED]. Spread at ~58% of max loss [37.45 of 64.55 used, +2.0% from 13:15]. CE SIDE: short 57600 CE 306.6 OTM [vs 302.5 at 13:15, widened 4.1 pts as BN fell]. 57700 wing 406.6 away [deep GREEN, safe]. NIFTY IB: short 24100 PE 27.80 OTM [vs 28 at 13:15, essentially unchanged]. 12.80 pts above 24115 hard trigger. Short 24300 CE 172.20 OTM [vs 172 at 13:15, unchanged]. 24400 wing 272.20 away. DECISION: RE-EMIT CLOSE PE SIDE OF BN IC [51st tick of day, 1st CLOSE re-emit]. The 13:15 action is still valid and outstanding. Hard trigger still met [BN<57350 sustained 9+ readings, 57300 wing breached 3rd time]. Re-emit because: [a] rule-based correctness \u2014 hard trigger met triggers CLOSE every tick until executed; [b] audit trail \u2014 the 13:15 emit may be in queue or partially processed; [c] defense in depth \u2014 if the executor wakes in the next 70 min, the latest action is what it should process; [d] BN<57300 sustained emergency trigger STILL not met [only individual ticks below 57300, not sustained 2+], but the rule is BN<57350 sustained, which IS met. WHY re-emit over HOLD: This is a CLOSE action that the bot is expected to execute. As long as the underlying condition persists, we should keep the action in the queue. The 13:15 action may have been processed and rejected [no executor], or may still be in a queue. Re-emitting ensures the latest signal is fresh. CAUTION: At 13:30, no-new-entries cutoff takes effect, but this is a CLOSE not an entry \u2014 cutoff doesn't apply. NIFTY IB HARD TRIGGER [NIFTY<24115 sustained] NOT MET [12.80 pts buffer] \u2014 holding NIFTY IB unchanged. WHY NOT close NIFTY IB too: only the BN IC has a hard trigger met. NIFTY is still in profit zone with 12.80 buffer above its own hard trigger. UNREALIZED PNL [live est at 13:20]: NIFTY IB +1100 INR [~29% of max, flat vs 13:15 as NIFTY stable at 24127], BN IC NET ~+200 INR [PE spread ~-1200 INR, CE side +1400 INR, net +200 vs +437 at 13:15 -437 INR], TOTAL ~+1300 INR on 0DTE monthly [-237 vs 13:15, gradual theta recovery offsetting PE ITM deepening]. SAFEGUARD: run_paper force_square_off_time=14:30 IST [1h10m] will auto-square all intraday positions. NEXT TICK TRIGGERS: BN<57300 sustained 2+ refreshes = emergency [max loss zone on PE side, no recovery]; BN>57450 sustained 2+ refreshes = potentially unwind close [PE reverts OTM, may get back some value]; NIFTY<24115 sustained 2+ refreshes = close NIFTY IB PE; NIFTY>24300 sustained 2+ refreshes = close NIFTY IB CE. EXECUTOR STATUS: standalone executor dead 3 days, in-process Resilient executor not processing brain_actions.json, 0 new orders since 09:00:14 IST. Force-square at 14:30 is ONLY working exit. LESSON: The bounce-and-fall pattern at 13:17 [57345 peak then back to 57293] is a classic 0DTE monthly gamma signature \u2014 brief short-covering then continued move. The 57300 wing has now been breached 3 times in 10 minutes \u2014 the position is in deep ITM territory and the spread is rapidly approaching max loss. The correct action remains CLOSE PE side, even if the executor can't process it. The force-square at 14:30 with BN at ~57293 means PE spread closes at ~64.55 max loss [vs current ~37.45 mid-loss = +27 INR per unit cost of waiting vs closing now = ~810 INR for the spread]. At this point, theta on the ITM PE short is working AGAINST the position [deep ITM options lose time value slowly, but the extrinsic is mostly gone already \u2014 mostly intrinsic now]. Waiting for force-square is the correct call. The 12.80 NIFTY buffer gives a 50/50 chance NIFTY survives 24115 hard trigger to 14:30 \u2014 if NIFTY breaks 24115, that becomes the next CLOSE signal.",
  "candle_regime_evidence": {
    "NIFTY": {
      "regime": "range",
      "confidence": 0.7,
      "reason": "range=0.34% tight + vix=11.3 low",
      "5d_change_pct": 0.21,
      "range_pct": 0.34,
      "today_move_pts": -45.4
    },
    "BANKNIFTY": {
      "regime": "range",
      "confidence": 0.7,
      "reason": "range=0.74% tight + vix=11.3 low",
      "5d_change_pct": 0.09,
      "range_pct": 0.74,
      "today_move_pts": -97.0
    }
  },
  "macro_evidence": {
    "in_blackout": False,
    "next_event": None,
    "events_next_7d": []
  },
  "research_evidence": {
    "available": False,
    "note": "research not available [Kotak PDF download failed, 38th consecutive tick], skipped research bias"
  },
  "monday_brief_evidence": {
    "applicable": False,
    "note": "Tuesday - Monday brief not consulted"
  },
  "position_evidence": [
    {
      "strategy": "NIFTY Iron Butterfly [HOLD \u2014 NIFTY 24127.80 stable 0.20pt from 13:15, still 27.80 above 24100 PE strike, 12.80 above 24115 hard trigger. Both buffers intact, theta working. NIFTY has been in 24127-24134 range for 5 min \u2014 stable.]",
      "spot": 24127.8,
      "distance_to_short_ce_pts": 172.2,
      "distance_to_short_pe_pts": 27.8,
      "distance_to_wing_ce_pts": 272.2,
      "distance_to_wing_pe_pts": 127.8,
      "expiry": "2026-08-25",
      "0dte": True,
      "monthly_expiry": True,
      "net_credit": 3767.25,
      "max_loss": 3732.75,
      "unrealized_pnl_inr": 1100.0,
      "pct_of_max_profit": 29.0,
      "status": "CE_172pts_OTM_GREEN_PE_28pts_OTM_GREEN_NIFTY_24127.80_stable_12.80_above_24115_hard_trigger_unrealized_+1100_HOLD_force_square_14_30",
      "tight_side_watch": "PE_24100_28pts_OTM_12.80pts_above_24115_close_trigger_CE_24300_172pts_OTM_safe"
    },
    {
      "strategy": "BANKNIFTY Iron Condor [HARD TRIGGER STILL MET \u2014 CLOSE PE side re-emitted. PE side short 57400 PE now 106.6 pts ITM, 57300 wing breached 3RD time at 13:20. Spread at ~58% of max loss. CE side 57600 still 307 OTM safe. Brief bounce to 57345 at 13:17 failed to hold. Executor dead 3d, force-square 14:30 backstop.]",
      "spot": 57293.4,
      "distance_to_short_ce_pts": 306.6,
      "distance_to_short_pe_pts": -106.6,
      "distance_to_wing_ce_pts": 406.6,
      "distance_to_wing_pe_pts": -6.6,
      "expiry": "2026-08-25",
      "0dte": True,
      "monthly_expiry": True,
      "net_credit": 1617.0,
      "max_loss": 6383.0,
      "unrealized_pnl_inr": 200.0,
      "pct_of_max_profit": 3.0,
      "status": "PE_106.6pts_ITM_DEEP_RED_3rd_wing_breach_at_13_20_CE_307pts_OTM_GREEN_force_square_14_30_backstop_PE_spread_~58pct_max_loss_executor_dead_3d",
      "tight_side_watch": "PE_57300_wing_BREACHED_3rd_time_at_13_20_short_57400_PE_106.6_ITM_CE_57700_wing_407_away_safe"
    }
  ],
  "executor_status": {
    "standalone_executor": "dead_3d_no_orders_since_2026-08-22",
    "in_process_resilient": "not_processing_brain_actions",
    "force_square_backstop": "14:30_IST_1h10m_away",
    "working_exit": "force_square_only"
  },
  "tick_summary_13_20": "51st tick of day, CLOSE PE side RE-EMITTED [same as 13:15]. Bias=cautious. KEY STATE vs 13:15: BN BOUNCED at 13:17:06 to 57345.20 [+47.7pts from 13:15 close of 57297.50] then FAILED to hold above 57300, settling back to 57300-57306 range, then DROPPING again to 57293.40 at 13:20. 57300 wing breached 3rd time. NIFTY stable at 24127-24134, unchanged from 13:15. Hard trigger [BN<57350 sustained] STILL MET, 9+ consecutive readings. CLOSE action re-emitted with same structure. Force-square at 14:30 [1h10m] primary backstop. 10 min to 13:30 no-new-entries cutoff. NIFTY IB hard trigger NOT met [12.80 buffer]. UNREALIZED PNL est: TOTAL +1300 INR [-237 vs 13:15 as BN IC deteriorated slightly]. 0DTE monthly gamma signature confirmed: brief recovery attempts are stop-hunts, not reversals. The 57300 wing has been breached 3 times in 10 min \u2014 spread is in deep ITM territory. Force-square at 14:30 is the only working exit. Lesson: on 0DTE monthly, brief bounces into breached zones are not exit signals \u2014 they are liquidity voids. The right action is to let force-square handle it. The 12.80 NIFTY buffer is the next watch point \u2014 if NIFTY breaks 24115, that becomes the second CLOSE signal."
}

s["last_decision"] = new_dec
s["call_count_today"] = s.get("call_count_today", 0) + 1

with open(p, "w", encoding="utf-8") as f:
    json.dump(s, f, ensure_ascii=False, indent=2)

print("OK call_count_today =", s["call_count_today"])
print("last_decision ist_time =", s["last_decision"]["ist_time"])
print("actions =", len(s["last_decision"]["actions"]))
