import json
import re
import os

path = r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json'

# Read the malformed file
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Strategy: extract all history objects by finding the pattern of ist_time + bias + note objects
# and reconstruct a clean structure

# First, find the position of the second "history" key (the real one)
# The first "history" at pos 9163 is the duplicate 12:10 entry
# The second "history" at pos 20479 is the real one with all the older history
# We want to merge: second_history_entries + first_history_entries + new 12:21 entry

# Find all "history" positions
history_positions = [m.start() for m in re.finditer(r'"history"\s*:\s*\[', content)]
print(f'Found {len(history_positions)} history keys at positions: {history_positions}')

# Extract the array contents of the SECOND history (the real one)
second_hist_start = history_positions[1]
# Find the matching close bracket
# Walk forward and count brackets
i = content.index('[', second_hist_start)
bracket_depth = 0
end_bracket = -1
for j in range(i, len(content)):
    c = content[j]
    if c == '[':
        bracket_depth += 1
    elif c == ']':
        bracket_depth -= 1
        if bracket_depth == 0:
            end_bracket = j
            break

second_hist_content = content[i:end_bracket+1]
print(f'Second history array length: {len(second_hist_content)}')

# Parse the second history list
try:
    second_history = json.loads(second_hist_content)
    print(f'Parsed {len(second_history)} history entries from second history')
except Exception as e:
    print(f'Failed to parse second history: {e}')
    second_history = []

# The first history (duplicate of 12:10) - extract manually since we know the 12:10 entry
# It's a single entry with: 2026-08-27T06:40:54Z, 2026-08-27 12:10:54, neutral, 1 action
first_hist_entry = {
    "ts": "2026-08-27T06:40:54Z",
    "ist_time": "2026-08-27 12:10:54",
    "bias": "neutral",
    "actions": [
        {
            "id": "act-1210BNFCL",
            "type": "CLOSE",
            "strategy": "iron_condor",
            "underlying": "BANKNIFTY",
            "expiry": "2026-08-27"
        }
    ],
    "note": "close_bnf_condor_hard_escalation_trigger_57700_breached_1210_lock_profit_hold_nifty_pe_buffer_39pt_comfortable"
}

# Build new 12:21 history entry
new_history_entry = {
    "ts": "2026-08-27T06:51:30Z",
    "ist_time": "2026-08-27 12:21:30",
    "bias": "cautious",
    "actions": [
        {
            "id": "act-1221BNFCLRE",
            "type": "CLOSE",
            "strategy": "iron_condor",
            "underlying": "BANKNIFTY",
            "expiry": "2026-08-27"
        }
    ],
    "note": "reissue_close_bnf_condor_1221_12_10_close_did_not_execute_ttl_expired_now_loss_cutting_bnf_98pt_below_57700_strike_hold_nifty_pe_buffer_46pt_comfortable_2h09m_to_force_square"
}

# Combine: new 12:21 first, then first_hist_entry (12:10), then all second_history entries
# Dedupe by (ist_time, note) to avoid duplicates
combined_history = [new_history_entry]
seen = set()
for entry in [first_hist_entry] + second_history:
    key = (entry.get('ist_time', ''), entry.get('note', ''))
    if key not in seen and entry.get('ist_time'):
        seen.add(key)
        combined_history.append(entry)

print(f'Combined history: {len(combined_history)} entries (new 12:21 + deduped history)')

# Build the new clean brain_state.json
new_state = {
    "today_date": "2026-08-27",
    "call_count_today": 25,
    "last_decision": {
        "ts": "2026-08-27T06:51:30Z",
        "ist_time": "2026-08-27 12:21:30",
        "bias": "cautious",
        "source": "mavis",
        "max_positions": 2,
        "actions": [
            {
                "id": "act-1221BNFCLRE",
                "type": "CLOSE",
                "strategy": "iron_condor",
                "underlying": "BANKNIFTY",
                "expiry": "2026-08-27",
                "legs": [
                    {"side": "BUY", "strike": 57900, "option_type": "CE", "qty": 30, "price": None},
                    {"side": "SELL", "strike": 58000, "option_type": "CE", "qty": 30, "price": None},
                    {"side": "BUY", "strike": 57700, "option_type": "PE", "qty": 30, "price": None},
                    {"side": "SELL", "strike": 57600, "option_type": "PE", "qty": 30, "price": None}
                ],
                "rationale": "REISSUE of 12:10 BNF CLOSE that did NOT execute. Bot log tail 12:19-12:21 shows zero close fills, SCAN still says skip: 2 open strategies >= max 2, TTL of 12:10 action (300s) expired at 12:15:54 without execution -- order_mgr did not pick it up, or it failed silently. This is now a LOSS-CUTTING reissue, not profit-locking: BNF spot 57601.60 (LiveIndia 12:21:18) is 98.40pt BELOW 57700 short PE strike (vs 34.20pt ITM at 12:10), BNF has fallen another 64.20pt in 11 minutes. BNF condor P&L: PE side loss ~60.91/unit (98.40 intrinsic vs 37.39 original credit) = -1827 INR; CE side gain ~55.90/unit (both OTM, time value decay) = +1677 INR; net ~-150 INR (was +1629 INR at 12:10 -- the lock-in window is gone). Reissuing with fresh TTL=300 to give the bot another chance. If THIS one also does not execute, the 14:30 force-square-off (2h09m away) is the backstop. BNF has made 3 consecutive lower intraday lows (57623, 57606, 57584) on 1m refreshes -- momentum is DOWN, not the morning oscillation pattern. Aug 26 pattern no longer applies (that was a brief ITM dip that recovered; this is a sustained break). NEW escalation trigger: BNF spot < 57500 (next major psychological level, 100pt below current 57700 strike) -- at that point the short PE is meaningfully ITM and the max loss cap of 201 INR is breached on a single leg. NIFTY condor: HOLD, PE buffer 46.60pt at 24146.60 (31.60pt above 15pt trigger, COMFORTABLE, recovered from 39.30pt at 12:10), CE buffer 153.40pt (very safe). NIFTY range regime intact, both legs OTM, no escalation. After BNF close: 1/2 cap, no new entry planned (1h09m to 13:30 cutoff insufficient for new setup + opening buffer).",
                "ttl_sec": 300
            }
        ],
        "note": "reissue_close_bnf_condor_1221_12_10_close_did_not_execute_ttl_expired_now_loss_cutting_bnf_98pt_below_57700_strike_hold_nifty_pe_buffer_46pt_comfortable_2h09m_to_force_square",
        "market_session": "regular",
        "vix": 11.18,
        "macro_in_blackout": False,
        "candle_regime_evidence": {
            "NIFTY": {
                "regime": "range",
                "confidence": 0.7,
                "last_close": 24146.4,
                "trend_5d": "flat",
                "change_5d_pct": -0.44,
                "range_pct": 0.68,
                "reason": "range=0.68% tight + vix=11.18 calm (1.0x multiplier); spot 24146.60 (LiveIndia 12:21:18) between shorts 24100/24300 -- RECOVERED +7.30pt from 12:10 tick (was 24139.30); PE buffer 39.30 -> 46.60pt (+7.30pt, now 31.60pt above 15pt trigger, COMFORTABLE), CE buffer 160.70 -> 153.40pt (-7.30pt, very safe). Both legs OTM, range regime well-centered. NIFTY 5d trend flat (-0.44% over 5d), no directional pressure."
            },
            "BANKNIFTY": {
                "regime": "range",
                "confidence": 0.7,
                "last_close": 57597.55,
                "trend_5d": "flat",
                "change_5d_pct": -0.28,
                "range_pct": 0.74,
                "reason": "range=0.74% tight + vix=11.18 calm (1.0x multiplier); spot 57601.60 (LiveIndia 12:21:18) BELOW short PE 57700 by 98.40pt -- deeper ITM than 12:10 (-64.20pt move in 11min); 3 consecutive lower intraday lows (57623, 57606, 57584) on 1m refreshes -- DOWNTREND, not morning oscillation. PE buffer -34.20 -> -98.40pt (-64.20pt worse in 11min), CE buffer 234.20 -> 298.40pt (+64.20pt safer). BNF condor P&L shifted from +1629 to ~-150 INR. 14:30 force-square-off in 2h09m, 13:30 no-new-entries in 1h09m. Brain reissues 12:10 CLOSE that did not execute."
            }
        },
        "macro_evidence": {
            "in_blackout": False,
            "upcoming_events": [
                {"name": "monthly_expiry_NIFTY", "datetime_ist": "2026-08-28 15:30", "importance": 2, "minutes_away": 1628},
                {"name": "india_gdp", "datetime_ist": "2026-08-29 17:30", "importance": 2, "minutes_away": 3188}
            ],
            "interpretation": "No near-term event risk. Monthly NIFTY expiry tomorrow 27h08m away. GDP 53h08m away. Both well outside 60min blackout window. Macro quiet, no defensive bias needed. ~2h09m to 14:30 force square-off, ~1h09m to 13:30 no-new-entries cutoff."
        },
        "research_evidence": {
            "available": False,
            "fallback": "Research PDF download still failing (kotak_research.download_latest_research_pdf:52 WARNING, fired again at 12:21:22). Candle+macro+VIX-only mode. VIX 11.18 (DOWN 0.02pt from 11.20 at 12:10, still well in calm range, 1.0x multiplier)."
        },
        "open_positions_summary": {
            "count": 2,
            "details": [
                "NIFTY 0DTE iron condor: short 24300CE/24100PE, long 24400CE/24000PE, width 100, 65 qty per leg, opened 09:30:32 IST at net credit 55.70/unit (max profit 3620 INR, max loss 2880 INR) - HOLD",
                "BANKNIFTY 0DTE iron condor: short 57900CE/57700PE, long 58000CE/57600PE, width 100, 30 qty per leg, opened 09:30:32 IST at net credit 93.29/unit (max profit 2799 INR, max loss 201 INR) - REISSUE CLOSE (12:10 close did not execute)"
            ],
            "spot_vs_strikes": {
                "nifty": "spot 24146.60 (LiveIndia 12:21:18) between shorts 24100/24300 -- 46.60pt from short PE, 153.40pt from short CE -- +7.30pt UP from 12:10 (was 39.30/160.70) -- PE buffer 39.30 -> 46.60pt (+7.30pt, now 31.60pt above 15pt trigger, COMFORTABLE), CE buffer 160.70 -> 153.40pt (-7.30pt, very safe). NIFTY recovered from 12:10 low, both legs OTM.",
                "banknifty": "spot 57601.60 (LiveIndia 12:21:18) BELOW short PE strike 57700 by 98.40pt -- 298.40pt from short CE -- -64.20pt DOWN from 12:10 (was -34.20/234.20) -- PE buffer -34.20 -> -98.40pt (-64.20pt WORSE, BNF DEEPER ITM, 3 consecutive lower intraday lows), CE buffer 234.20 -> 298.40pt (+64.20pt safer). 12:10 CLOSE did NOT execute. Brain reissues with fresh TTL."
            },
            "unrealized_pnl_inr_estimate": {
                "nifty_condor_ltp_based": "~2050",
                "banknifty_condor_ltp_based": "~-150 (was +1629 at 12:10, profit gone, small loss now)",
                "total_approx_before_close": "~1900",
                "note": "NIFTY condor still solidly in green, ~+2050 INR LTP-based mark (UP from 12:10 +1800 by ~+250 INR on +7.30pt spot recovery which is roughly delta-neutral, slight theta positive). BNF condor: -64.20pt move toward short PE significantly compresses PE leg. At 57601.60, short 57700 PE intrinsic 98.40pt, long 57600 PE intrinsic 1.60pt. Net PE value = 96.80pt vs 37.39 original credit = 59.41pt cost per unit = 1782 INR. CE side gains (both OTM, time value decay). Net BNF P&L ~-150 INR. Lock in this loss by reissuing CLOSE. After BNF close, NIFTY condor remains at 46.60pt PE buffer (comfortable)."
            },
            "max_reached": True,
            "max_positions_limit": 2,
            "note": "At cap 2/2 before close. Issuing REISSUE CLOSE on BNF condor (12:10 did not execute, now loss-cutting). After BNF close: 1/2 cap, no new entry planned (1h09m to 13:30 cutoff, insufficient for new setup + opening buffer). NIFTY condor HOLD: PE buffer 46.60pt (31.60pt above trigger, comfortable), range regime intact, both legs OTM."
        },
        "bias_decision": "cautious",
        "risk_budget_pct": 0.0,
        "risk_budget_reasoning": "Risk budget = 0% for new capital: (a) at cap 2/2 before BNF close, (b) only 1h09m to 13:30 no-new-entries cutoff, (c) ~2h09m to 14:30 force-square-off insufficient for new 0DTE trade + opening buffer, (d) BNF breaking down with 12:10 close not executed, (e) macro quiet but BNF momentum negative. Brain escalation to cautious because 12:10 CLOSE on BNF did not execute and BNF is now deeper ITM. New escalation trigger: BNF spot < 57500 (next major psychological level). Bot stop-loss + 14:30 force-square-off remain primary defenses for both condors.",
        "planned_setup": None,
        "decision_summary": "REISSUE CLOSE BNF condor (HOLD NIFTY) at 12:21 IST, regular session, ~2h09m to 14:30 force square-off, ~1h09m to 13:30 no-new-entries cutoff. The 12:10 brain decision was a CLOSE on BNF condor that did NOT execute: bot log tail 12:19-12:21 shows no close fills, SCAN still says skip 2/2, TTL of 12:10 action (300s) expired at 12:15:54. Tick-over-tick vs 12:10: VIX 11.20 -> 11.18 (-0.02, still calm 1.0x), NIFTY 24139.30 -> 24146.60 (+7.30pt RECOVERY, PE buffer 39.30 -> 46.60pt [+7.30pt, 31.60pt above 15pt trigger, COMFORTABLE], CE buffer 160.70 -> 153.40pt [-7.30pt, very safe]), BANKNIFTY 57665.80 -> 57601.60 (-64.20pt, PE buffer -34.20 -> -98.40pt [-64.20pt WORSE, BNF DEEPER ITM by 98.40pt below 57700 strike, 3 consecutive lower intraday lows, DOWNTREND], CE buffer 234.20 -> 298.40pt [+64.20pt safer]). BNF condor P&L: shifted from +1629 INR (12:10) to ~-150 INR (now small loss), lock-in window gone. 12:10 close was profit-locking; 12:21 reissue is loss-cutting. Aug 26 pattern no longer applies (that was brief ITM dip + recovery; this is sustained break). NEW escalation trigger: BNF spot < 57500. Reissuing with fresh TTL=300 to give bot another chance to execute; if THIS one also does not execute, 14:30 force-square-off is the backstop. NIFTY condor HOLD: PE buffer 46.60pt (31.60pt above 15pt trigger, comfortable, range regime well-centered, both legs OTM). After BNF close: 1/2 cap, no new entry planned (1h09m to 13:30 cutoff)."
    },
    "history": combined_history,
    "last_updated_ist": "2026-08-27 12:21:30"
}

# Backup the original first
backup_path = path + '.broken_backup'
if not os.path.exists(backup_path):
    with open(backup_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f'Backed up broken file to {backup_path}')

# Write the new clean state
with open(path, 'w', encoding='utf-8') as f:
    json.dump(new_state, f, indent=2, ensure_ascii=False)

print(f'Wrote clean brain_state.json: call_count_today=25, last_decision=12:21, history={len(combined_history)} entries')

# Verify it loads
with open(path, 'r', encoding='utf-8') as f:
    verify = json.load(f)
print(f'Verification: loaded OK, top-level keys: {list(verify.keys())}')
print(f'  call_count_today: {verify["call_count_today"]}')
print(f'  history entries: {len(verify["history"])}')
print(f'  last_decision ist_time: {verify["last_decision"]["ist_time"]}')
print(f'  last_decision bias: {verify["last_decision"]["bias"]}')
print(f'  last_decision actions: {len(verify["last_decision"]["actions"])}')
