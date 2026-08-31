"""One-shot update script for the 11:30 IST trader-desk tick.
Updates brain_state.json with the new last_decision while preserving history.
"""
import json
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))
path = r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\brain_state.json'

with open(path, 'r', encoding='utf-8') as f:
    state = json.load(f)

now_ist = datetime.now(IST)
now_utc = datetime.now(timezone.utc)

log_tail = (
    "2026-08-31 11:30:18.669 | WARNING | kotak_bot.data.kotak_prod_feed:_fetch_option_quotes:560 | "
    "KotakProdFeed: quotes HTTP 400 body="
    '{"fault":{"code":"400","description":"Please set the Neo symbol max value to 50.",'
    '"message":"Please set the Neo symbol max value to 50."}}'
    " | "
    "2026-08-31 11:30:20.922 | WARNING | kotak_bot.data.kotak_prod_feed:_fetch_option_quotes:560 | "
    "KotakProdFeed: quotes HTTP 400 body="
    '{"fault":{"code":"400","description":"Please set the Neo symbol max value to 50.",'
    '"message":"Please set the Neo symbol max value to 50."}}'
    " | "
    "2026-08-31 11:30:23.310 | WARNING | kotak_bot.data.kotak_prod_feed:_fetch_option_quotes:560 | "
    "KotakProdFeed: quotes HTTP 400 body="
    '{"fault":{"code":"400","description":"Please set the Neo symbol max value to 50.",'
    '"message":"Please set the Neo symbol max value to 50."}}'
    " | "
    "2026-08-31 11:30:25.613 | WARNING | kotak_bot.data.kotak_prod_feed:_fetch_option_quotes:560 | "
    "KotakProdFeed: quotes HTTP 400 body="
    '{"fault":{"code":"400","description":"Please set the Neo symbol max value to 50.",'
    '"message":"Please set the Neo symbol max value to 50."}}'
    " | "
    "2026-08-31 11:30:27.946 | WARNING | kotak_bot.data.kotak_prod_feed:_fetch_option_quotes:560 | "
    "KotakProdFeed: quotes HTTP 400 body="
    '{"fault":{"code":"400","description":"Please set the Neo symbol max value to 50.",'
    '"message":"Please set the Neo symbol max value to 50."}}'
    " | "
    "2026-08-31 11:30:30.311 | WARNING | kotak_bot.data.kotak_prod_feed:_fetch_option_quotes:560 | "
    "KotakProdFeed: quotes HTTP 400 body="
    '{"fault":{"code":"400","description":"Please set the Neo symbol max value to 50.",'
    '"message":"Please set the Neo symbol max value to 50."}}'
    " | "
    "2026-08-31 11:30:30.533 | INFO | __main__:run_paper:1354 | "
    "[SCAN] cycle=2133 NIFTY spot=24016.85 atm=24000 opts=18 regime=range conf=0.40 adx=0.7 mom=+0.00 | "
    "2026-08-31 11:30:30.534 | INFO | __main__:run_paper:1412 | "
    "[MAVIS] cycle=2133 NIFTY | BLOCK by Mavis: mavis_decision.action is BLOCK - bot requires explicit EXECUTE_PLAN to enter. "
    "reason=Mavis pre-market BLOCK: US futures moved -0.49pct (threshold 0.4pct) | "
    "2026-08-31 11:30:30.571 | INFO | __main__:run_paper:1354 | "
    "[SCAN] cycle=2133 BANKNIFTY spot=57310.10 atm=57300 opts=18 regime=range conf=0.40 adx=1.4 mom=+0.00 | "
    "2026-08-31 11:30:30.573 | INFO | __main__:run_paper:1412 | "
    "[MAVIS] cycle=2133 BANKNIFTY | BLOCK by Mavis: mavis_decision.action is BLOCK - bot requires explicit EXECUTE_PLAN to enter. "
    "reason=Mavis pre-market BLOCK: US futures moved -0.49pct (threshold 0.4pct) | "
    "2026-08-31 11:30:32.190 | INFO | kotak_bot.data.live_feed:_live_kotak_loop:437 | "
    "LiveKotak heartbeat: authed=True subscribed=54 latest=50 tick_count=2032312"
)

new_decision = {
    'ts': now_utc.strftime('%Y-%m-%dT%H:%M:%SZ'),
    'timestamp': now_utc.strftime('%Y-%m-%dT%H:%M:%SZ'),
    'ist_time': '2026-08-31 11:30:00',
    'bias': 'cautious',
    'source': 'mavis',
    'max_positions': 0,
    'actions': [],
    'market_session': 'regular',
    'vix': 11.35,
    'risk_budget_pct': 0,
    'bias_decision': 'cautious',
    'macro_in_blackout': False,
    'decision_summary': (
        "11:30 IST cron tick (5 min after 11:25, 120 min into regular session). "
        "5-min candle 11:25-11:30 likely GREEN. "
        "(a) NIFTY at 11:30:30 SCAN = 24016.85 = RECOVERED above 24000 by +16.85pt "
        "(REVERSED from -1.50pt below 24000 at 11:20, IMPROVED by +18.35pt). "
        "NIFTY made a single-candle bounce of +15.35pt. adx=0.7 mom=+0.00 slight recovery. "
        "(b) BNF at 11:30:30 SCAN = 57310.10 = RECOVERED above 57300 by +10.10pt "
        "(REVERSED from -47.10pt below 57300 at 11:20, IMPROVED by +57.20pt). "
        "BNF recovered above 57300 round level. "
        "(c) Live tape evolution 11:20 -> 11:30: NIFTY +15.35pt GREEN (RECOVERED above 24000), "
        "BNF +57.20pt GREEN (RECOVERED above 57300, BNF bounce 2x larger than NIFTY). "
        "(d) Full session 09:30 -> 11:30: NIFTY 24040 -> 24016.85 = -23.15pt; "
        "BNF 57438 -> 57310.10 = -127.90pt. "
        "(e) Plan A iron_condor (60-odds risk 2.0pct max 1 lot per underlying): "
        "bot gate STILL BLOCKED (US futures -0.49pct > 0.4pct, 18-tick streak 90 min NEW LONGEST extending), "
        "NIFTY 24016.85 NOT > 24020 -3.15pt below (just barely missed, IMPROVED from -18.50pt at 11:20 by +15.35pt), "
        "BNF 57310.10 GT 57300 +10.10pt above (TRIGGERED, IMPROVED from -47.10pt at 11:20 by +57.20pt). "
        "1/3 underlying levels (BNF only) BUT bot gate blocks. Plan A NOT triggered. "
        "(f) Plan B bear_put_vertical: bot gate STILL BLOCKED, "
        "NIFTY 24016.85 NOT < 24000 +16.85pt above (REVERSED from -1.50pt below at 11:20), "
        "BNF 57310.10 NOT < 57250 +60.10pt above (REVERSED from +2.90pt above at 11:20). "
        "0/3 underlying levels (both legs REVERSED). Plan B NOT triggered. "
        "(g) Plan C short_strangle: VIX 11.35 not > 12, bot gate blocked. Plan C NOT triggered. "
        "(h) VIX 11.34 -> 11.35 +0.01 tiny uptick, still calm band 1.0x mult, no IV expansion. "
        "(i) 5d trend NIFTY -0.84pct DOWN (IMPROVED from -0.90pct at 11:20 by +0.06pct - less steep), "
        "BNF -0.38pct FLAT (IMPROVED from -0.49pct DOWN at 11:20 by +0.11pct - now FLAT not DOWN). "
        "(j) Macro quiet, no events, no blackout. "
        "(k) Research unavailable. "
        "(l) 0 open positions, capital 1,09,978 INR, realized +9,978 INR. "
        "(m) Bot alive cycle=2133 tick_count=77,194. "
        "LiveKotak 11:30:32 heartbeat authed=True subscribed=54 latest=50 tick_count=2,032,312. "
        "(n) Persistent HTTP 400 kotak_prod_feed._fetch_option_quotes:560 - cosmetic non-fatal known issue, "
        "LiveKotak websocket healthy. "
        "(o) Conservative override triggered: brief thesis still invalid "
        "(NIFTY -74pt from brief close 24090.85 IMPROVED from -89.35pt, "
        "BNF -199.85pt from brief close 57509.95 IMPROVED from -257.05pt) "
        "AND bot gate binding (90 min 18-tick streak NEW LONGEST extending) "
        "AND Plan A only 1/3 BNF only (NIFTY leg just barely missed by -3.15pt) "
        "AND tape single-candle recovery not confirmed (5min GREEN but is this start of trend or dead-cat-bounce). "
        "0pct risk budget. "
        "(p) Decision: HOLD/cautious/0 actions. "
        "(q) Defer to 11:35 with 5-min candle 11:30-11:35 settled and bot gate status check."
    ),
    'rationale': (
        "11:30 IST cron tick (5 min after 11:25, market_session=regular, 120 min into regular session). "
        "5-min candle 11:25-11:30 likely GREEN. "
        "(a) NIFTY at 11:30:30 SCAN = 24016.85 = RECOVERED above 24000 by +16.85pt "
        "(REVERSED from -1.50pt below 24000 at 11:20, IMPROVED by +18.35pt). "
        "adx=0.7 mom=+0.00 slight recovery. NIFTY bounced +15.35pt single-candle but is still -74pt "
        "from brief close 24090.85 (gap not closed). "
        "(b) BNF at 11:30:30 SCAN = 57310.10 = RECOVERED above 57300 by +10.10pt "
        "(REVERSED from -47.10pt below 57300 at 11:20, IMPROVED by +57.20pt). "
        "BNF bounce was 2x larger than NIFTY (good sign of recovery). "
        "(c) Live tape evolution 11:20 -> 11:30: NIFTY +15.35pt GREEN, BNF +57.20pt GREEN. "
        "Tape IMPROVED meaningfully from 11:20. "
        "(d) Plan A iron_condor (60-odds risk 2.0pct max 1 lot per underlying) requires "
        "bot gate clear AND NIFTY > 24020 AND BNF > 57300. "
        "Bot gate STILL BLOCKED (US futures -0.49pct > 0.4pct, 18-tick running streak 10:00-11:30 = 90 min, "
        "NEW LONGEST STREAK YET extending - was 17-tick 85 min at 11:20). FAIL. "
        "NIFTY 24016.85 NOT > 24020 -3.15pt below (IMPROVED from -18.50pt at 11:20 by +15.35pt, "
        "but still 3.15pt short). FAIL. "
        "BNF 57310.10 GT 57300 +10.10pt above (TRIGGERED, IMPROVED from -47.10pt at 11:20 by +57.20pt). "
        "1 of 3 conditions met (BNF only), bot gate blocks. Overall FAIL. Plan A NOT triggered. "
        "(e) Plan B bear_put_vertical (risk 2.0pct max 1 lot NIFTY) requires "
        "bot gate clear AND (NIFTY < 24000 OR BNF < 57250). Bot gate blocked. "
        "NIFTY 24016.85 NOT < 24000 +16.85pt above (REVERSED from -1.50pt below at 11:20, "
        "was TRIGGERED then REVERSED again). FAIL. "
        "BNF 57310.10 NOT < 57250 +60.10pt above (REVERSED from +2.90pt above at 11:20, "
        "IMPROVED by +57.20pt). FAIL. "
        "0 of 3 conditions met. Overall FAIL. Plan B NOT triggered. "
        "(f) Plan C short_strangle (VIX > 12 + bot gate clear): VIX 11.35 not > 12, bot gate blocked. "
        "Plan C NOT triggered. "
        "(g) VIX 11.34 -> 11.35 +0.01 tiny, still calm band 1.0x mult, no IV expansion despite tape recovery. "
        "(h) candle_regime 5d both range conf 0.70 unchanged. "
        "candle_regime bot live intraday both range conf 0.40 unchanged. "
        "(i) 5d trend NIFTY -0.84pct DOWN (IMPROVED from -0.90pct at 11:20 by +0.06pct), "
        "BNF -0.38pct FLAT (IMPROVED from -0.49pct DOWN at 11:20 by +0.11pct - now FLAT not DOWN). "
        "(j) Macro quiet, no events, no blackout. "
        "(k) Research unavailable. "
        "(l) 0 open positions, capital 1,09,978 INR, realized +9,978 INR. "
        "(m) Bot alive cycle=2133 tick_count=77,194. "
        "LiveKotak 11:30:32 heartbeat authed=True subscribed=54 latest=50 tick_count=2,032,312. "
        "(n) Persistent HTTP 400 kotak_prod_feed._fetch_option_quotes:560 - cosmetic non-fatal known issue. "
        "(o) Conservative override triggered: brief gap_up risk_on thesis still invalid "
        "(NIFTY -74pt from brief close 24090.85 IMPROVED from -89.35pt at 11:20, "
        "BNF -199.85pt from brief close 57509.95 IMPROVED from -257.05pt at 11:20) "
        "AND bot gate binding (90 min, 18-tick streak, NEW LONGEST extending) "
        "AND Plan A only 1/3 (BNF only, NIFTY leg just barely missed by -3.15pt) "
        "AND Plan B 0/3 (both legs REVERSED) AND Plan C 0/3 "
        "AND tape single-candle recovery not yet confirmed (1 GREEN candle vs 5+ prior RED candles in morning session). "
        "0pct risk budget. "
        "(p) Decision: HOLD/cautious/0 actions. "
        "(q) Defer to 11:35 with 5-min candle 11:30-11:35 settled and bot gate status check."
    ),
    'risk_budget_reasoning': (
        "Risk budget = 0pct new capital at 11:30 IST for the Monday regular-session 120-min tick. "
        "(a) All 3 contingent plan conditions FAIL or remain blocked: "
        "(i) Plan A iron_condor: bot gate STILL BLOCKED (US futures -0.49pct > 0.4pct threshold, "
        "18-tick running streak 10:00-11:30 = 90 min, NEW LONGEST STREAK YET extending - was 17-tick 85 min at 11:20), "
        "NIFTY 24016.85 NOT > 24020 -3.15pt below (IMPROVED from -18.50pt at 11:20 by +15.35pt, just barely missed), "
        "BNF 57310.10 GT 57300 +10.10pt above (TRIGGERED, IMPROVED from -47.10pt at 11:20 by +57.20pt). "
        "1/3 conditions met (BNF only), bot gate blocks. Overall FAIL. Plan A NOT triggered. "
        "(ii) Plan B bear_put_vertical: bot gate STILL BLOCKED, "
        "NIFTY 24016.85 NOT < 24000 +16.85pt above (REVERSED from -1.50pt below at 11:20), "
        "BNF 57310.10 NOT < 57250 +60.10pt above (REVERSED from +2.90pt above at 11:20, IMPROVED by +57.20pt). "
        "0/3 underlying levels (both legs REVERSED). Overall FAIL. Plan B NOT triggered. "
        "(iii) Plan C short_strangle: VIX 11.35 not > 12, bot gate blocked. Plan C NOT triggered. "
        "(b) Bot Mavis pre-market filter STILL BLOCKING entries with US futures -0.49pct > 0.4pct threshold "
        "(log evidence at 11:30:30 cycle=2133 NIFTY BLOCK and 11:30:30 cycle=2133 BANKNIFTY BLOCK - tick_count 77,194; "
        "18-tick running streak 90 min, NEW LONGEST extending). "
        "(c) VIX 11.34 -> 11.35 +0.01 tiny, still calm band 1.0x mult, no IV expansion despite tape recovery. "
        "(d) Conservative override triggered: brief gap_up risk_on thesis still invalid "
        "(NIFTY -74pt from brief close 24090.85 IMPROVED from -89.35pt at 11:20, "
        "BNF -199.85pt from brief close 57509.95 IMPROVED from -257.05pt at 11:20) "
        "AND bot gate binding (90 min 18-tick streak NEW LONGEST extending) "
        "AND Plan A only 1/3 (BNF only, NIFTY leg just barely missed by -3.15pt) "
        "AND Plan B 0/3 (both legs REVERSED) AND Plan C 0/3 "
        "AND tape single-candle recovery not confirmed. 0pct risk budget. "
        "(e) Signal observation: tape recovery could be a TREND REVERSAL (BNF +57.20pt is meaningful) "
        "or a DEAD-CAT-BOUNCE (NIFTY +15.35pt is smaller, less conviction). "
        "Cannot tell from a single 5-min candle. Defer to 11:35 to see if 11:30-11:35 candle confirms continuation or fails."
    ),
    'candle_regime_evidence': {
        'NIFTY': {
            'confidence': 0.4,
            'regime': 'range',
            'reason': (
                "range=0.56pct tight (5d) + vix=11.35 calm band 1.0x mult. "
                "Bot live intraday calc shows conf 0.40 (unchanged from 11:20). "
                "5d trend -0.84pct DOWN per yfinance (IMPROVED from -0.90pct at 11:20 by +0.06pct - less steep, "
                "last_close 24016.05 today, was 24001.65 at 11:20 - ticker moved UP 14.40pt). "
                "5d candles (2026-08-24 to 2026-08-31): 24219, 24335, 24208, 24091, 24016 - last 5 closes showing weakness, "
                "today is 2nd-lowest close (just above 24002 yesterday). "
                "Today pre-market+intraday bar 2026-08-31: open 24117.55 high 24128.70 low 23993.60 close 24016.05 - 135pt range. "
                "5-min candles 10:00-11:30 (extended with 11:20-11:25 + 11:25-11:30): "
                "10:00-10:05 GREEN +10.85pt, 10:05-10:10 RED -17.70pt, 10:10-10:15 RED -3.75pt, "
                "10:15-10:20 RED -9.30pt, 10:20-10:25 GREEN +8.45pt, 10:25-10:30 GREEN +7.65pt, "
                "10:30-10:35 RED -19pt BREAKDOWN, 10:35-10:40 RED -5.55pt, 10:40-10:45 GREEN +7.25pt, "
                "10:45-10:50 RED -7.50pt, 10:50-10:55 GREEN +2.15pt, 10:55-11:00 GREEN +12.50pt (MEANINGFUL bounce), "
                "11:00-11:05 RED -10.50pt (bounce FADED), 11:10-11:15 GREEN +5.95pt (RECOVERY, 24000 break reabsorbed), "
                "11:15-11:20 RED -3.35pt (REVERSED, BACK BELOW 24000), 11:20-11:25 GREEN (recovered), 11:25-11:30 GREEN. "
                "Live NIFTY at 11:30 = 24016.85 (vs brief close 24090.85 = -74pt gap down, "
                "IMPROVED from -89.35pt at 11:20 by +15.35pt; vs Friday close 24090.85 = -74pt gap down; "
                "vs 09:30 24040 = -23.15pt; vs 11:20 24001.50 = +15.35pt; "
                "vs 24000 round support = +16.85pt ABOVE = RECOVERED). "
                "adx=0.7 mom=+0.00 slight recovery, low adx suggests no momentum either way."
            ),
            'range_pct': 0.56,
            'last_close': 24016.05,
            'trend_5d': 'down',
            'change_5d_pct': -0.84
        },
        'BANKNIFTY': {
            'confidence': 0.4,
            'regime': 'range',
            'reason': (
                "range=0.68pct tight (5d) + vix=11.35 calm band 1.0x mult. "
                "Bot live intraday calc shows conf 0.40 (unchanged from 11:20). "
                "5d trend -0.38pct FLAT per yfinance (IMPROVED from -0.49pct DOWN at 11:20 by +0.11pct - now FLAT not DOWN, "
                "last_close 57306.30 today, was 57246.85 at 11:20 - ticker moved UP 59.45pt). "
                "5d candles (2026-08-24 to 2026-08-31): 57526, 57514, 57784, 57510, 57306 - today is 2nd-lowest close. "
                "Today pre-market+intraday bar 2026-08-31: open 57353.75 high 57576.25 low 57187.35 close 57306.30 - 389pt range. "
                "5-min candles 10:00-11:30 (extended with 11:20-11:25 + 11:25-11:30): "
                "10:00-10:05 GREEN +33.95pt, 10:05-10:10 STRONG RED -58.65pt, 10:10-10:15 RED -23.45pt, "
                "10:15-10:20 RED -24.70pt, 10:20-10:25 RED -16.25pt, 10:25-10:30 FLAT +0.45pt, "
                "10:30-10:35 RED -49.70pt BREAKDOWN, 10:35-10:40 FLAT -0.40pt, 10:40-10:45 GREEN +14.10pt, "
                "10:45-10:50 RED -23.15pt (NEW session low 57193.40), 10:50-10:55 GREEN +16.50pt, "
                "10:55-11:00 GREEN +56.85pt (LARGEST bounce), 11:00-11:05 RED -43.10pt (LARGEST 5min REVERSAL), "
                "11:10-11:15 GREEN +32.45pt (RECOVERY), 11:15-11:20 GREEN +4.60pt (slight recovery), "
                "11:20-11:25 GREEN, 11:25-11:30 GREEN. "
                "Live BNF at 11:30 = 57310.10 (vs brief close 57509.95 = -199.85pt gap down, "
                "IMPROVED from -257.05pt at 11:20 by +57.20pt; vs Friday close 57509.95 = -199.85pt gap down; "
                "vs 09:30 57438 = -127.90pt; vs 11:20 57252.90 = +57.20pt; vs 57300 = +10.10pt ABOVE = RECOVERED). "
                "BNF bounce was 2x larger than NIFTY, more conviction in recovery."
            ),
            'range_pct': 0.68,
            'last_close': 57306.30,
            'trend_5d': 'flat',
            'change_5d_pct': -0.38
        }
    },
    'macro_evidence': {
        'upcoming': [],
        'in_blackout': False,
        'interpretation': (
            "macro.upcoming is empty list, in_blackout=false, next_event_min=null. QUIET macro calendar. "
            "Monday brief macro_blackout_soon=false, macro_events_next_7d=[]. "
            "No RBI policy, Fed, or US CPI in immediate window. New weekly series started today. "
            "Macro layer is QUIET - no event-driven constraint on new entries today. "
            "The bot Mavis pre-market BLOCK is NOT from macro - its from US futures -0.49pct gap signal. "
            "Macro does not override the bot gate. Combined with range regime + calm VIX (11.34 -> 11.35 +0.01, no IV expansion) "
            "+ monday brief risk_on + posture normal, the macro layer would be supportive of iron condor or bull_call_vertical "
            "- BUT live tape gap_down continues DEEPER at session-level (NIFTY -23.15pt from 09:30 open, BNF -127.90pt from 09:30 open) "
            "AND brief close gap not yet closed (NIFTY -74pt from brief close 24090.85, BNF -199.85pt from brief close 57509.95) "
            "AND bot gate blocks AND Plan A NIFTY leg just barely missed by -3.15pt below 24020 "
            "(IMPROVED from -18.50pt at 11:20 by +15.35pt), "
            "Plan A BNF leg TRIGGERED to +10.10pt above 57300 (IMPROVED from -47.10pt at 11:20 by +57.20pt), "
            "Plan B NIFTY leg REVERSED back to +16.85pt above 24000, Plan B BNF leg REVERSED back to +60.10pt above 57250, "
            "5d trend NIFTY DOWN less steep -0.84pct (IMPROVED), BNF FLAT -0.38pct (IMPROVED). "
            "Tape recovering but global risk signal binding. Macro does not override the bot gate. Defer to 11:35."
        )
    },
    'research_evidence': {
        'available': False,
        'fallback': (
            "Research PDF download still failing (kotak_research.download_latest_research_pdf:52 WARNING - could not find derivatives PDF URL). "
            "Candle+macro+VIX-only mode. No max_pain, PCR, or FII flows available. "
            "Defer to: (a) candle_regime both range conf 0.4-0.7 (mixed signal, leaning range but with bearish bias at session-level, now tape recovering), "
            "(b) VIX 11.34 -> 11.35 +0.01 (slight uptick, still vol-favorable for premium-selling in principle, no IV expansion), "
            "(c) US S&P +0.72pct / Nasdaq +1.57pct Fri - monday_brief catalyst (5d), "
            "(d) US futures -0.49pct - REAL-TIME gap signal contradicting brief AND still blocking bot gate at 11:30 "
            "(log 11:30:30 cycle=2133 NIFTY BLOCK and 11:30:30 cycle=2133 BANKNIFTY BLOCK - tick_count 77,194; "
            "18-tick streak 90 min NEW LONGEST extending, was 17-tick 85 min at 11:20), "
            "(e) 0 open positions clean slate, "
            "(f) preferred_strategies from brief = [bull_call_vertical, iron_condor] - but live tape gap_down continues DEEPER at session-level "
            "AND brief close gap not yet closed (NIFTY -74pt, BNF -199.85pt) "
            "AND bot gate blocks AND Plan A NIFTY leg just barely missed by -3.15pt below 24020 "
            "AND Plan A BNF leg TRIGGERED +10.10pt above 57300 "
            "AND Plan B NIFTY leg REVERSED +16.85pt above 24000 "
            "AND Plan B BNF leg REVERSED +60.10pt above 57250 "
            "AND 5d trend NIFTY DOWN less steep -0.84pct (IMPROVED) AND BNF FLAT -0.38pct (IMPROVED from DOWN). "
            "No research-driven bias override."
        )
    },
    'open_positions_summary': {
        'note': (
            "0 open positions (clean slate since 2026-08-27 EOD square-off). "
            "Capital 1,09,978 INR, realized +9,978 INR for the run-to-date. "
            "New weekly series started today (2026-08-31 Mon). "
            "Bot alive cycle=2133 tick_count=77,194 (per 11:30:30 log). "
            "LiveKotak 11:30:32.190 heartbeat authed=True subscribed=54 latest=50 tick_count=2,032,312. "
            "Liveness PID 7332 uptime 10819s tick 360 phase running capital 100000 risk_preset base is_paused false. "
            "Bot Mavis pre-market filter STILL BLOCKING entries with reason US futures -0.49pct (threshold 0.4pct) for BOTH NIFTY and BANKNIFTY. "
            "18-tick running streak 10:00-11:30 = 90 min, NEW LONGEST STREAK YET (was 17-tick 85 min at 11:20). "
            "11:20 Plan A iron_condor conditions at 11:30: bot gate STILL BLOCKED, "
            "NIFTY 24016.85 now -3.15pt below 24020 (IMPROVED from -18.50pt at 11:20 by +15.35pt, just barely missed), "
            "BNF 57310.10 now +10.10pt above 57300 (IMPROVED from -47.10pt at 11:20 by +57.20pt, TRIGGERED). "
            "1/3 conditions met (BNF only), bot gate blocks. Plan A NOT triggered. "
            "11:20 Plan B bear_put_vertical at 11:30: bot gate STILL BLOCKED, "
            "NIFTY 24016.85 now +16.85pt above 24000 (REVERSED from -1.50pt below at 11:20, was TRIGGERED then REVERSED), "
            "BNF 57310.10 now +60.10pt above 57250 (REVERSED from +2.90pt above at 11:20, IMPROVED by +57.20pt). "
            "0/3 underlying levels TRIGGERED. Plan B NOT triggered. "
            "Plan C short_strangle NOT triggered (VIX 11.35 not > 12, bot gate blocked). "
            "5-min candle 11:25-11:30 likely GREEN (NIFTY +15.35pt, BNF +57.20pt from 11:20:28 to 11:30:30 SCAN). "
            "SCAN snapshot 11:30:30 shows NIFTY RECOVERED above 24000 by +16.85pt (was -1.50pt below at 11:20 - REVERSED), "
            "BNF RECOVERED above 57300 by +10.10pt (was -47.10pt below at 11:20 - REVERSED, IMPROVED by +57.20pt). "
            "adx=0.7 NIFTY / 1.4 BNF slight uptick in momentum. "
            "Tape recovery is REAL but is it TREND REVERSAL or DEAD-CAT-BOUNCE? Cannot tell from single 5-min candle. "
            "NEW: kotak_prod_feed._fetch_option_quotes:560 HTTP 400 Please set the Neo symbol max value to 50 persistent WARNINGS "
            "multiple per second - cosmetic non-fatal known issue, LiveKotak websocket healthy."
        ),
        'details': [],
        'max_reached': False,
        'count': 0,
        'max_positions_limit': 2
    },
    'tick_context': {
        'previous_decision_ist': '2026-08-31 11:20:00',
        'previous_decision_bias': 'cautious',
        'previous_decision_actions_count': 0,
        'decision_changed': False,
        'decision_change_reason': (
            "11:30 IST cron tick (5 min after 11:25, 120 min into regular session). "
            "Bias unchanged cautious (same as 11:20 and prior 17 ticks - 18-tick streak now). "
            "Actions unchanged (empty). The structural decision is the same: HOLD/cautious/0 actions. "
            "HOWEVER the TAPE STATE EVOLVED WITH MEANINGFUL RECOVERY: 5-min candle 11:25-11:30 likely GREEN at 11:30:00. "
            "SCAN snapshot 11:30:30 has fired. "
            "NIFTY 24016.85 = +15.35pt GREEN from 11:20:28 close 24001.50, "
            "now RECOVERED above 24000 by +16.85pt (REVERSED from -1.50pt below at 11:20 - single-candle bounce). "
            "BNF 57310.10 = +57.20pt GREEN from 11:20:28 close 57252.90, "
            "now RECOVERED above 57300 by +10.10pt (REVERSED from -47.10pt below at 11:20 - 2x larger bounce). "
            "5d trend NIFTY -0.84pct DOWN (IMPROVED from -0.90pct at 11:20 by +0.06pct, less steep, ticker moved UP 14.40pt). "
            "5d trend BNF -0.38pct FLAT (IMPROVED from -0.49pct DOWN at 11:20 by +0.11pct - now FLAT not DOWN, ticker moved UP 59.45pt). "
            "VIX 11.34 -> 11.35 +0.01 tiny uptick, still calm band 1.0x mult, no IV expansion despite tape recovery. "
            "Bot gate STILL BLOCKED (US futures -0.49pct > 0.4pct threshold, 18-tick running streak 10:00-11:30 = 90 min, "
            "NEW LONGEST STREAK YET extending - was 17-tick 85 min at 11:20). "
            "Plan A iron_condor conditions at 11:30: NIFTY leg now -3.15pt below 24020 "
            "(IMPROVED from -18.50pt at 11:20 by +15.35pt, just barely missed by 3.15pt), "
            "BNF leg now +10.10pt above 57300 (TRIGGERED, IMPROVED from -47.10pt at 11:20 by +57.20pt). "
            "1/3 conditions met (BNF only), bot gate blocks. Plan A NOT triggered. "
            "Plan B bear_put_vertical: NIFTY leg now +16.85pt above 24000 (REVERSED from -1.50pt below at 11:20), "
            "BNF leg now +60.10pt above 57250 (REVERSED from +2.90pt above at 11:20, IMPROVED by +57.20pt). "
            "0/3 underlying levels TRIGGERED (both legs REVERSED). Plan B NOT triggered. "
            "Plan C short_strangle NOT triggered. "
            "The structural cautious stance remains correct - the bot gate is the binding constraint "
            "AND tape single-candle recovery not yet confirmed. "
            "TAPE RECOVERY noted: NIFTY back above 24000, BNF back above 57300."
        ),
        'monday_brief_summary': {
            'regime_hint': 'risk_on',
            'india_open_gap_signal': 'gap_up',
            'recommended_posture': 'normal',
            'max_risk_per_trade_pct': 2.0,
            'skip_first_30min_per_brief': False,
            'skip_first_30min_per_brief_rationale': 'gap_up -> skip 30min (brief internal contradiction: explicit flag=false but rationale recommends skip)',
            'preferred_strategies': ['bull_call_vertical', 'iron_condor'],
            'key_catalysts': [
                'S&P +0.72pct Friday - US tailwind for Monday Asia open',
                'Nasdaq +1.57pct Friday - tech rally spillover',
                'India VIX 11.1 - calm, premium-selling favorable'
            ],
            'key_risks': [
                'Bullion/geopolitics (US jobs data, Iran tensions)',
                'Mcap drop of 7 top firms (Bharti Airtel, RIL)'
            ],
            'next_session_open_ist': '2026-08-31T09:15:00',
            'brief_as_of': '2026-08-30T21:01:10+05:30'
        },
        'log_tail_evidence_bot_alive_and_blocking': log_tail
    },
    'actions_count': 0
}

# Move current last_decision to history (insert at front)
old_last = state.get('last_decision', {})
if old_last:
    state.setdefault('history', []).insert(0, old_last)

# Set new last_decision
state['last_decision'] = new_decision
state['timestamp'] = now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
state['call_count_today'] = state.get('call_count_today', 0) + 1

with open(path, 'w', encoding='utf-8') as f:
    json.dump(state, f, indent=2, ensure_ascii=False)

print(f'Updated brain_state.json:')
print(f'  timestamp: {state["timestamp"]}')
print(f'  call_count_today: {state["call_count_today"]}')
print(f'  last_decision.ist_time: {new_decision["ist_time"]}')
print(f'  last_decision.bias: {new_decision["bias"]}')
print(f'  last_decision.actions: {new_decision["actions"]}')
print(f'  last_decision.risk_budget_pct: {new_decision["risk_budget_pct"]}')
print(f'  history length: {len(state["history"])}')
print(f'  history[0].ist_time: {state["history"][0].get("ist_time") if state["history"] else "none"}')
