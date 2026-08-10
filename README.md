# Kotak Neo Trading Bot

> **Production-grade Indian options + intraday trading bot for Kotak Neo (zero brokerage). 30+ features. Paper-trading first, live-ready.**

---

## TL;DR

- Trades **NIFTY** and **BANKNIFTY** options only (3rd-week expiry, weekly rolls).
- 10 strategies, regime-based selector, **30+ production features**.
- Risk engine with **3 adaptive presets** (aggressive / base / defensive) that switch per cycle.
- **LLM news judge** using **MiniMax M2.7-highspeed** (real reasoning, not just keywords).
- Full **intel layer**: OI / GEX / max-pain / performance attribution / alpha decay / auto-params tuning.
- **Telegram command surface** for live control: `/status /positions /pnl /regime /oi /perf /force /close /pause /resume`.
- **Hourly P&L snapshots**, **voice alerts**, **chart alerts**, **compliance PDF** at EOD.
- **Mavis co-pilot** (AI advisor) reads state every 10 min during market hours and sends insights.
- Live UAT websocket auth works; UAT tick delivery is in-progress (synthetic fallback keeps the bot functional).
- Built end-to-end in one go because the user said "do everything".

---

## 1. What is this bot?

A small Python program that:

1. Connects to **Kotak Neo** (TOTP + MPIN auth).
2. Subscribes to live ticks for NIFTY and BANKNIFTY (or runs a synthetic feed in paper mode).
3. Detects the current **market regime** (trending / range / volatile / event).
4. Picks the **best strategy** for that regime.
5. Sizes the trade via a **variable risk engine**.
6. Places the order(s) — either via Kotak Neo's matching engine (live) or against a synthetic book (paper).
7. Monitors open positions for **smart exits** (target / stop / time / regime flip / IV crush).
8. Sends **Telegram alerts** (text + voice + chart) on every meaningful event.
9. Runs an **intel layer** (OI walls, GEX, performance attribution, alpha decay) that tunes the bot in real time.
10. Closes everything at 3:15 PM IST and sends a **daily report** at 3:30 PM.

**Why these two underlyings only?** NIFTY (75 lot) and BANKNIFTY (30 lot) are the deepest, most liquid index options in India. Tight spreads, no stock-specific risk, easy to test strategies.

---

## 2. End-to-end flow (what, why, how)

### 2.1 One scan cycle (every 30s during market hours)

```
                ┌─────────────────────────────────────────────┐
                │  for each symbol in (NIFTY, BANKNIFTY):    │
                └──────────────────────┬──────────────────────┘
                                       │
                                       ▼
   ┌───────────────────────────────────────────────────────────────┐
   │  1. SPOT CHECK — feed.get_ltp(symbol) returns 0?             │
   │     WHY: skip if data layer hasn't ticked yet (warm-up)      │
   │     HOW: synthetic feed emits spot every 0.5s; live UAT WS   │
   │          streams ticks via on_message callback                │
   └──────────────────────────────────┬────────────────────────────┘
                                       │
                                       ▼
   ┌───────────────────────────────────────────────────────────────┐
   │  2. STRIKE DISCOVERY — fetch LTPs for 9 strikes ATM ±4      │
   │     WHY: iron condor needs ±2 wings; jade/butterfly ±2–3;   │
   │          OI-aware strategies need walls + max-pain            │
   │     HOW: synthetic emits `NIFTY10AUG2625000CE` (dated) for  │
   │          each of 9 strikes; live UAT scrip master will too   │
   │     (FIXED 2026-08-10: was using `NIFTY25000CE` (no date) →  │
   │      silent 4h of no trades, all get_ltp returned 0)         │
   └──────────────────────────────────┬────────────────────────────┘
                                       │
                                       ▼
   ┌───────────────────────────────────────────────────────────────┐
   │  3. REGIME DETECTION — RegimeDetector.detect(momentum, vix) │
   │     WHY: strategy selection is regime-driven                  │
   │     HOW: ADX proxy from |momentum| (no candle history needed)│
   │          → if adx ≥ 25 → TRENDING                            │
   │          → if vix > 18 OR iv_rank > 70 + adx < 20 → VOLATILE│
   │          → else → RANGE                                      │
   │     (FIXED 2026-08-10: was always "range" with 0.4 conf     │
   │      because df=None → adx=0 → no real regime ever detected) │
   └──────────────────────────────────┬────────────────────────────┘
                                       │
                                       ▼
   ┌───────────────────────────────────────────────────────────────┐
   │  4. NEWS + EVENT CHECK                                      │
   │     WHY: avoid trading into a news shock; bias direction    │
   │     HOW: MacroCalendar blocks entries <15min before high-   │
   │          importance events (RBI / Fed / Budget / CPI / expiry)│
   │          LLMJudge (MiniMax M2.7) rates each headline for    │
   │          sentiment / relevance / urgency; aggregates into    │
   │          news_sentiment for SignalContext                    │
   └──────────────────────────────────┬────────────────────────────┘
                                       │
                                       ▼
   ┌───────────────────────────────────────────────────────────────┐
   │  5. SIGNAL CONTEXT — packages all the above into a struct   │
   │     WHY: strategies need a single object to make decisions  │
   │     HOW: SignalContext(symbol, spot, vix, iv_rank, adx,    │
   │          trend_strength, regime, timestamp, strikes,         │
   │          option_ltps, news_sentiment, news_urgency,          │
   │          upcoming_event, minutes_to_event)                   │
   └──────────────────────────────────┬────────────────────────────┘
                                       │
                                       ▼
   ┌───────────────────────────────────────────────────────────────┐
   │  6. STRATEGY SELECTION — StrategySelector.select(ctx, ...)  │
   │     WHY: best strategy depends on regime + signals + perf  │
   │     HOW: prioritized list per regime:                       │
   │          range    → iron_condor > iron_butterfly > jade_...  │
   │          trending → bull_call_vertical > long_call (or bear)│
   │          volatile → long_straddle > jade_lizard              │
   │          event    → event_straddle (if <30min to event)     │
   │     Returns TradePlan(strategy, legs[4], target, stop, ...)│
   └──────────────────────────────────┬────────────────────────────┘
                                       │
                                       ▼
   ┌───────────────────────────────────────────────────────────────┐
   │  7. RISK CHECK — RiskEngine.check_new_trade(plan, regime, ..)│
   │     WHY: every cap is checked BEFORE the order, not after    │
   │     HOW: pick_preset(regime, confidence, vix, perf_streak)   │
   │          → 'aggressive' / 'base' / 'defensive'               │
   │          → check per-trade cap, daily cap, position cap,    │
   │            cooldown, market hours, square-off time, etc.    │
   │     Returns RiskDecision(allowed, qty, max_loss)            │
   └──────────────────────────────────┬────────────────────────────┘
                                       │
                                       ▼
   ┌───────────────────────────────────────────────────────────────┐
   │  8. EXECUTE — OrderManager.execute_plan(plan, qty)         │
   │     WHY: build the right symbol format + send to broker    │
   │     HOW: format_symbol(NIFTY, 2026-08-10, 24600, CE)       │
   │          → "NIFTY10AUG2624600CE"                             │
   │          for 1-leg directional: NeoClient places BRACKET    │
   │          order (server-side SL + target + trailing)          │
   │          for multi-leg: regular LIMIT orders, fill in       │
   │          sequence via PaperClient._try_fill or NeoClient.     │
   │          placeorder                                          │
   └──────────────────────────────────┬────────────────────────────┘
                                       │
                                       ▼
   ┌───────────────────────────────────────────────────────────────┐
   │  9. ALERT + JOURNAL — TelegramAlerter.trade_opened(plan)    │
   │     WHY: user is away / sleeping / at work; needs push      │
   │     HOW: text message with strategy/legs/target/stop/reason│
   │          + Windows SAPI TTS → WAV → Telegram voice message  │
   │          + matplotlib chart of strikes/spot at entry        │
   │          + TradeJournal records entry to data_cache/journal/│
   └──────────────────────────────────┬────────────────────────────┘
                                       │
                                       ▼
   ┌───────────────────────────────────────────────────────────────┐
   │ 10. SCAN COMPLETE — last_scan = now, sleep 5s, repeat       │
   └───────────────────────────────────────────────────────────────┘
```

### 2.2 Continuous loops (independent of scan)

```
┌─ SMART EXIT LOOP ─────────────────────────────────────────────────┐
│  Every scan cycle, for each open trade:                          │
│    compute current P&L (mark-to-market from feed.get_ltp)        │
│    compute hold time                                              │
│    compute current regime (re-detect for the underlying)         │
│    if hold_min >= min_hold_before_smart_exit_sec (5 min)          │
│    AND evaluate_exit(plan, pnl, pnl_pct, hold, regime, ...) == true│
│    → close_trade + record P&L + send voice/text alert            │
│  Exit rules:                                                       │
│    - target hit (95% of plan.target)                              │
│    - stop hit (95% of plan.stop)                                 │
│    - time decay (≤30 min to expiry, <50% of target)               │
│    - max hold (1.5x expected_hold_minutes, <70% target)           │
│    - regime flip (range strategy in trending market)               │
│    - IV crush (long premium, iv dropped >20%)                      │
│    - partial profit (50% at 50% of target)                       │
└──────────────────────────────────────────────────────────────────┘

┌─ MARK-TO-MARKET + ANOMALY DETECTION ─────────────────────────────┐
│  Every cycle:                                                      │
│    compute_pnl(all positions) → total + per-symbol + per-underlying│
│    if |Δ P&L| > Rs.500 in last 5 cycles → Telegram alert          │
│    if |Δ spot| > 0.5% in 2.5s → Telegram alert                  │
│    if volume > 3x avg → Telegram alert                          │
│  All alerts have 5-min cooldown per key                          │
└──────────────────────────────────────────────────────────────────┘

┌─ POSITION RECONCILIATION ────────────────────────────────────────┐
│  Every 5 min:                                                      │
│    diff = reconcile(broker_positions, internal_trade_positions)│
│    if actionable diff (broker_only or internal_only):            │
│      send Telegram warn                                          │
│    save to data_cache/reconcile.jsonl (audit log)               │
│  Filters out stale qty_mismatch from old double-up              │
└──────────────────────────────────────────────────────────────────┘

┌─ HOURLY P&L SNAPSHOT ────────────────────────────────────────────┐
│  Top of every hour:                                                │
│    msg = capital / cash / used / realized / unrealized /         │
│          trades_today / preset / open positions (with each)      │
│    chart = generate_daily_chart(trades.csv) → PNG               │
│    send text + photo to Telegram                                │
└──────────────────────────────────────────────────────────────────┘

┌─ MAVIS CO-PILOT ────────────────────────────────────────────────┐
│  Every 10 min (cron):                                              │
│    read paper_state.json + log tail + performance metrics       │
│    call MiniMax M2.7-highspeed with context                     │
│    send 2-3 actionable insights to Telegram                     │
│  Examples: "Position limit breach — verify", "IV spike suggests │
│  hedging", "Iron condor short_delta 0.16 too high for current    │
│  volatility"                                                       │
└──────────────────────────────────────────────────────────────────┘

┌─ EOD AUTO SQUARE-OFF ────────────────────────────────────────────┐
│  At 15:15 IST:                                                     │
│    if is_square_off_time:                                        │
│      close all open trades via market orders                    │
│  Reason: SEBI intraday rule + avoid next-day gap risk           │
└──────────────────────────────────────────────────────────────────┘

┌─ DAILY REPORT ──────────────────────────────────────────────────┐
│  At 15:30 IST:                                                     │
│    send text: capital / P&L / trades / preset / open positions  │
│    send performance attribution: per-strategy Sharpe, win rate │
│    send alpha decay alerts: strategies with Sharpe < -0.1      │
│    send auto-tune recommendations for tomorrow                   │
│    generate compliance PDF (SEBI audit pack) → send as document │
│    send daily P&L chart                                          │
└──────────────────────────────────────────────────────────────────┘
```

---

## 3. Architecture overview

```
┌────────────────────────────────────────────────────────────────────┐
│                          ENTRY POINT                                │
│  python -m kotak_bot paper   (or live)                            │
│  → kotak_bot/__main__.py:run_paper()                              │
└────────────────────────┬───────────────────────────────────────────┘
                         │
        ┌────────────────┼─────────────────┐
        │                │                 │
        ▼                ▼                 ▼
   ┌─────────┐    ┌────────────┐    ┌────────────┐
   │ BROKER  │    │   FEED     │    │  ALERTS    │
   │  layer  │    │  layer     │    │  layer     │
   │         │    │            │    │            │
   │Paper or │    │ Synthetic  │    │ Telegram   │
   │NeoClient│    │ or Live WS │    │ + voice    │
   │  (UAT)  │    │            │    │ + chart    │
   └────┬────┘    └─────┬──────┘    └─────┬──────┘
        │               │                │
        └───────────────┼────────────────┘
                        │
                        ▼
┌────────────────────────────────────────────────────────────────────┐
│                          PIPELINE                                  │
│                                                                     │
│  ┌─────────────┐   ┌──────────────┐   ┌────────────┐              │
│  │  REGIME     │──▶│  STRATEGY    │──▶│   RISK     │              │
│  │  DETECTOR   │   │  SELECTOR    │   │  ENGINE    │              │
│  │ (RegimeDet) │   │(StratSel)    │   │(RiskEng)   │              │
│  └─────────────┘   └──────────────┘   └─────┬──────┘              │
│         ▲                  ▲                │                    │
│         │                  │                ▼                    │
│         │            ┌─────┴─────┐    ┌──────────────┐            │
│         │            │  STRATEGIES│    │  ORDER       │            │
│         │            │  10 plays  │───▶│  MANAGER     │            │
│         │            │  advanced  │    │ (ExecPlan)   │            │
│         │            └────────────┘    └──────┬───────┘            │
│         │                                       │                │
│         │              ┌────────────────────────┘                │
│         │              │                                          │
│         │              ▼                                          │
│         │       ┌────────────┐                                   │
│         └───────│  EXECUTE   │                                   │
│                 │  (broker) │                                   │
│                 └─────┬──────┘                                   │
│                       │                                          │
└───────────────────────┼──────────────────────────────────────────┘
                        │
        ┌───────────────┼──────────────────┐
        │               │                  │
        ▼               ▼                  ▼
   ┌─────────┐    ┌──────────────┐    ┌────────────┐
   │  POST   │    │   SMART      │    │  INTEL     │
   │ TRADE   │    │   EXIT       │    │  LAYER     │
   │  (P&L)  │    │  (every 30s) │    │ (always)   │
   └────┬────┘    └──────┬───────┘    └─────┬──────┘
        │               │                  │
        └───────────────┼──────────────────┘
                        │
                        ▼
            ┌──────────────────────┐
            │  TELEGRAM ALERTS     │
            │  hourly P&L          │
            │  voice on fill       │
            │  chart on EOD        │
            │  compliance PDF      │
            └──────────────────────┘
```

---

## 4. Components (the what + why + how)

### 4.1 Broker layer (`kotak_bot/broker/`)

**`PaperClient`** — what: simulates fills from a synthetic tick stream (or real LTP if you `inject_tick`). Why: lets the whole bot run end-to-end without a live broker. How: tracks a virtual `cash` and `positions` dict, fills LIMIT orders when tick crosses price (within 0.5% of LTP for paper realism), fills MARKET orders with 5-bps slippage, persists state to `data_cache/paper_state.json` so restart preserves positions.

**`NeoClient`** — what: thin wrapper over `neo_api_client` v2. Why: encapsulates the 2 SDK init bugs (`consumer_key` and `access_token` must be the same value, `neo_fin_key` is the hardcoded constant `"neotradeapi"`) and adds the bracket/cover/AMO/iceberg/scrip-master/audit/margin helpers. How: TOTP login → MPIN validate → standard CRUD on orders/positions/quotes, plus bracket order placement, market protection, scrip search, WebSocket on_message → Tick dispatch.

**`base.py`** — what: abstract `BrokerClient` + `Order` / `Position` / `Tick` dataclasses. Why: same interface for both Paper and Neo. How: `place_order(order, bracket=None, cover_sl=None)` — PaperClient accepts but ignores; NeoClient translates to API params.

### 4.2 Data layer (`kotak_bot/data/`)

**`LiveFeed`** — what: unified tick source. Why: same `feed.get_ltp(symbol)` works for synthetic and live. How: synthetic loop emits 2 ticks/sec with geometric Brownian motion + regime switching (range/trending/volatile), 9 strikes (ATM ±4), with dated symbol format `NIFTY10AUG2625000CE`. Live UAT mode subscribes to NIFTY/BANKNIFTY index tokens (26000/26009) via NeoClient WebSocket; falls back to synthetic if no ticks within 30s. Maintains `_price_history[20]` for momentum proxy.

**`historical.py`** — what: fetches 1-min historical candles. Why: backtesting needs history. How: yfinance first (free, no creds), then TrueData (paid), then nselib (free Indian), then Dhan (free with creds).

**`macro_calendar.py`** — what: hardcoded list of 21 RBI / Fed / US-CPI / Budget / monthly-expiry events for 2026. Why: avoid trading into high-impact events; weight directional bias. How: `get_event_window(now, ±30min)` returns event info if we're within the window; main loop blocks new entries <15min before high-importance events.

### 4.3 Signals (`kotak_bot/signals/`)

**`TechnicalAnalyzer`** — what: computes 60+ indicators (RSI, MACD, ADX, ATR, Supertrend, BBands, EMA, candlestick patterns). Why: some strategies need multi-indicator confluence. How: pandas-ta on a 1-min candle buffer (paper mode generates the candles from tick stream).

**`RegimeDetector`** — what: classifies market into `trending` / `range` / `volatile` / `unknown`. Why: strategy selection is regime-driven. How: 3-tier decision tree on ADX, VIX, IV rank. When `df=None` (no candle history), uses momentum proxy `|momentum| × 5000` capped at 50 — so a 0.5% tick move = ADX 25 (trending threshold).

**`llm_judge.py`** — what: LLM news judge. Why: FinBERT alone is too weak for Indian markets news. How: calls `https://agent.minimax.io/mavis/api/v1/llm/v1/messages` with model `MiniMax-M2.7-highspeed` (our own model), 30 RPM rate limit, response cache (10 min TTL), direct httpx with `x-api-key` + `Authorization: Bearer <jwt>` headers. Returns `{sentiment, relevance, urgency, direction, rationale, affected}`. Falls back to keyword scoring if API fails.

**`signals_news_init.py`** — what: lazy init helpers. Why: don't load FinBERT/LLM at import time. How: `get_news_pipeline(cfg)`, `get_llm_judge(cfg)` return None if not configured.

### 4.4 Strategies (`kotak_bot/strategy/`)

**`base.py`** — `SignalContext` (all info a strategy needs), `TradePlan` (output), `BaseStrategy` abstract.

**`directional.py`** — DirectionalDebitStrategy (1-leg directional with bracket).

**`premium_selling.py`** — IronCondorStrategy (4 legs, range), ShortStrangleStrategy (2 legs, range, undefined risk).

**`event_play.py`** — EventStraddleStrategy (RBI / Fed / Budget / expiry play).

**`advanced.py`** — 8 more strategies:
- `BullCallVerticalStrategy` (bullish, defined risk, 2 legs)
- `BearPutVerticalStrategy` (bearish, defined risk, 2 legs)
- `IronButterflyStrategy` (range, ATM-anchored, high prob)
- `JadeLizardStrategy` (high IV, short put + short call spread)
- `LongStraddleStrategy` (volatile, pre-news)
- `CalendarSpreadStrategy` (range, time-decay edge)
- `LongCallStrategy` (strong uptrend)
- `LongPutStrategy` (strong downtrend)

**`selector.py`** — picks the best strategy per cycle based on regime + signal context:
- Event imminent (≤30 min) → event_straddle
- Range → iron_condor > iron_butterfly > jade_lizard > short_strangle > calendar
- Trending up → bull_call_vertical > long_call
- Trending down → bear_put_vertical > long_put
- Volatile → long_straddle > jade_lizard
- Unknown → falls back to range plays

### 4.5 Risk engine (`kotak_bot/risk/engine.py`)

**`RiskEngine`** — what: gates every trade. Why: capital preservation is job #1. How: 3 presets, each with its own caps:

| Preset | Per-trade | Daily | Max trades/day | Lots | When |
|---|---|---|---|---|---|
| `aggressive` | 2% or ₹2,000 | 5% or ₹5,000 | 10 | 1-4 | trending + high conf + winning streak |
| `base` | 1% or ₹1,500 | 3% or ₹3,000 | 6 | 1-3 | default |
| `defensive` | 0.5% or ₹500 | 1.5% or ₹1,500 | 3 | 1 | volatile + low conf + losing streak |

Preset selection logic:
- regime == trending + conf ≥ 0.7 → aggressive
- regime == volatile → defensive
- vix > 20 → defensive
- vix < 10 → aggressive (capped to base otherwise)
- 3+ wins in a row → aggressive
- 2+ losses → defensive

Checks: market hours, paused state, square-off time, daily/weekly/monthly loss caps, max consecutive losses, max trades today, per-trade cap.

### 4.6 Execution (`kotak_bot/execution/`)

**`OrderManager`** — what: translates a `TradePlan` into 1+ broker orders. Why: paper and live brokers have the same interface, so this works for both. How:
- For 1-leg directional: passes `bracket=BracketOrderSpec(entry, SL, target, trailing)` to NeoClient (server-side SL+target+trailing). PaperClient accepts but ignores.
- For multi-leg defined-risk (iron condor, vertical): places LIMIT orders sequentially, applies format_symbol to each.
- Closes via market order.
- Tracks `ManagedTrade` with `trade_id` (UUID), `orders[]`, `pnl`, hold time, target/stop hit, exit reason.

**`smart_exit.py`** — what: continuous exit evaluation. Why: not just SL/target — need time decay, regime flip, IV crush, partial profit. How: `evaluate_exit(plan, pnl, pnl_pct, hold_min, regime, ...)` returns `ExitSignal(should_exit, reason, exit_pct, urgency)`. Exits: target 95%, stop 95%, time decay ≤30 min to expiry, max hold 1.5x, regime flip, IV crush 20%, partial 50% at 50% of target. Also: `bs_greeks()` for BS-approximated delta/gamma/vega/theta (swap to Dhan real greeks when creds added); `aggregate_portfolio_greeks()` for portfolio-level exposure.

### 4.7 Intel layer (`kotak_bot/intel/`)

**`oi_analytics.py`** — OI / GEX / max-pain. Given `{symbol: Tick}` from `feed.get_oi_map()`:
- `oi_walls()` — max call OI (resistance) + max put OI (support)
- `max_pain()` — strike with max total OI (options expire here)
- `pcr()` — put/call ratio (>1 bullish, <0.7 bearish)
- `gex()` — net gamma exposure (positive = long gamma = mean-reverting, negative = short gamma = explosive)
- `oi_aware_strike_selection()` — aligns iron condor strikes with OI walls

**`performance.py`** — per-strategy metrics:
- `PerformanceTracker` — rolling 20-trade window, win rate, avg P&L, Sharpe, best/worst, avg hold, persisted to `logs/performance.csv`
- `AlphaDecayDetector` — flags a strategy as decayed if rolling Sharpe < -0.1 with 5+ trades
- `AutoParamsTuner` — adjusts `target_rr`, `wing_width`, `stop_loss_multiplier`, `max_lots` based on rolling Sharpe (4 presets: aggressive / base / tighten / defensive)

**`reconcile.py`** — `reconcile_positions(broker_pos, internal_pos)` → `{matched, broker_only, internal_only, qty_mismatch}`. Filters out stale mismatches; only alerts on actionable diffs.

**`journal.py`** — `TradeJournal` (auto-captures chart at every entry → `data_cache/journal/`), `CompliancePDF` (SEBI audit pack at EOD via reportlab), `MultiBrokerRouter` (Kotak + Dhan + Upstox stubs, `pick_broker()` for lowest priority, `find_arbitrage()` for cross-broker spreads).

**`mark_to_market.py`** — `compute_pnl()` (per-symbol + per-underlying + total), `AnomalyDetector` (P&L swing >Rs.500, price spike >0.5%, volume spike >3x, all with 5-min cooldown), `OIHeatmapGenerator` (matplotlib bar chart of CE/PE OI per strike).

### 4.8 Alerts (`kotak_bot/alerts/`)

**`telegram.py`** — `TelegramAlerter`:
- `send(text)` — text message
- `send_voice(wav_path)` — Telegram voice message
- `send_photo(png_path)` — Telegram photo with caption
- `synthesize_voice(text, label)` — Windows SAPI TTS → WAV file
- `generate_daily_chart(trades_csv)` — matplotlib cumulative P&L + per-leg bars → PNG
- `trade_opened(plan)` / `trade_closed(pnl, reason)` — typed helpers
- `daily_report(summary)` — full report at 3:30 PM with chart + voice

**`telegram_commands.py`** — `TelegramCommandHandler` polls Telegram every 5s for user commands:
- `/status` — bot state, P&L, positions, preset, pause reason
- `/positions` — current open positions
- `/pnl` — day/week/month P&L
- `/regime` — current market regime + ADX + VIX + IV rank
- `/oi NIFTY` (or BANKNIFTY) — resistance / support / max-pain / PCR / interpretation
- `/perf` — per-strategy Sharpe, win rate, avg P&L
- `/force NIFTY` (or BANKNIFTY) — manual paper trade (bypasses gates for testing)
- `/close` — force-close all open positions
- `/pause [reason]` / `/resume` — toggle new entries
- `/ping` / `/time` / `/help`

**`email.py`** — Gmail SMTP fallback (not heavily used; Telegram is primary).

---

## 5. Why each preset matters (the risk adaptation)

```
Market:  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
         ┌──────────────┐    ┌──────────────┐
         │  TRENDING    │    │  RANGE       │
         │  (ADX > 25)  │    │  (ADX < 20)  │
         └──────┬───────┘    └──────┬───────┘
                │                   │
                ▼                   ▼
        ┌──────────────┐    ┌──────────────┐
        │ AGGRESSIVE   │    │    BASE      │
        │ 2% per trade │    │ 1% per trade │
        │ 5% daily     │    │ 3% daily     │
        │ 10 trades    │    │ 6 trades     │
        │ Lots 1-4     │    │ Lots 1-3     │
        └──────┬───────┘    └──────┬───────┘
                │                   │
       ┌────────┴────────┐   ┌──────┴────────┐
       │ bull_call_v    │   │ iron_condor  │
       │ bear_put_v     │   │ iron_butterfly│
       │ long_call      │   │ jade_lizard  │
       │ long_put       │   │ short_strangle│
       └────────────────┘   └───────────────┘
```

The bot *adapts in real time*:
- ADX < 20 + VIX > 20 → defensive (0.5% per trade)
- 3 wins in a row → bump to aggressive
- 2 losses in a row → drop from aggressive to base
- Hold time > 1.5x expected → close if <70% of target
- Regime flips mid-trade → close

This is **variable** not hardcoded. Every cycle picks the right preset based on context.

---

## 6. How to run

### 6.1 First time

```bash
# clone
git clone https://github.com/SaiNihal2622/kotak-neo-trading-bot.git
cd kotak-neo-trading-bot

# venv
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

# credentials (from your .env, gitignored)
cp config/credentials.env.template config/credentials.env
# edit credentials.env with your Kotak API key, MPIN, TOTP secret, Telegram token + chat_id
```

### 6.2 Start

```bash
# paper mode (default)
.venv\Scripts\python -m kotak_bot paper

# check status
.venv\Scripts\python -m kotak_bot status

# reset paper state
.venv\Scripts\python -m kotak_bot reset

# dashboard
.venv\Scripts\python -m streamlit run dashboard/app.py --server.port=8501 --server.headless=true
```

### 6.3 Going live (when ready)

1. Get static IP registered with SEBI (>10 orders/sec)
2. Sign Algo ID with exchange (currently `KOTAK_NEO_BOT_V1`)
3. Add real money to Kotak Neo account
4. Edit `config/settings.yaml`:
   - `mode: live` (instead of `paper`)
   - `broker.type: neo` (instead of `paper`)
   - `broker.environment: prod` (instead of `uat`)
5. Start with very small capital (₹50K-100K) for first week

---

## 7. Configuration (`config/settings.yaml`)

All knobs are in `settings.yaml`. Notable sections:

```yaml
broker:
  paper_capital: 100000          # paper account size
risk:
  position_cap: 2               # max open positions
  cooldown_per_symbol_sec: 600  # 10 min between trades on same symbol
  hourly_pnl_report: true       # send P&L to Telegram every hour
  base: { ... }                 # base preset caps
  aggressive: { ... }           # aggressive preset caps
  defensive: { ... }            # defensive preset caps
strategy:
  iron_condor: { wing_width: 100, ... }
  iron_butterfly: { ... }
  bull_call_vertical: { wing_width: 100, ... }
  # ... 10 strategies total
data:
  live_feed: synthetic          # 'synthetic' | 'live_uat' (real ticks from Kotak)
alerts:
  telegram: { enabled: true }
  voice: { enabled: true }
  visual_report: { enabled: true }
```

---

## 8. Operating guide

### What to do each morning before market opens (9:00 IST)
- Check Telegram for the 8:30 cron "Bot is up" message
- `/status` to confirm capital, position count, preset
- `/regime` to see current ADX / VIX / IV rank

### What to do while market is open
- **Don't watch the screen.** The bot sends you everything.
- On any unusual Telegram alert, `/status` to investigate.
- `/force NIFTY` if you want to manually open a position.
- `/close` if you want to flatten everything.

### What to do at EOD (after 3:30 PM)
- Read the daily report (text + chart + compliance PDF)
- Check performance attribution (`/perf`): is each strategy making money?
- Check alpha decay alert: are any strategies decaying?
- Review auto-tune recommendations for tomorrow

### Weekly review
- Run walk-forward backtest on last week's data
- Review compliance PDFs
- Check that the bot didn't drift (manual trades, settings changes)

---

## 9. Going to production checklist

| Item | Status | Notes |
|---|---|---|
| Paper trading | ✅ | runs continuously, 30+ features live |
| Real Kotak Neo auth | ✅ | UAT TOTP+MPIN verified 2026-08-06 |
| Live UAT websocket ticks | 🟡 | auth works, tick delivery wip (synthetic fallback) |
| Risk engine | ✅ | 3 presets, all caps configurable |
| Telegram alerts | ✅ | text + voice + chart on every event |
| Compliance log | ✅ | every order audited to `data_cache/audit_log.jsonl` |
| Algo ID registered with SEBI | ❌ | need to sign paperwork |
| Static IP for >10 orders/sec | ❌ | currently 6 trades/day max |
| Live capital in account | ❌ | using ₹100K paper only |
| Live broker in `mode: neo` | ❌ | flip in settings.yaml when ready |

**Current safety rails:**
- Daily cap 3% base (₹3,000 on ₹100K)
- Per-trade cap 1% base (₹1,000 on ₹100K)
- Max 6 trades/day base
- Position cap 2
- EOD square-off 15:15

These are *configurable* per the user's risk preferences — not hardcoded.

---

## 10. What was added in each round (the journey)

| Date | Round | What |
|---|---|---|
| 2026-08-06 | Initial build | 13 modules, 63 files, smoke test passed |
| 2026-08-06 | UAT auth | Found 2 SDK init bugs in `neo_api_client`, fixed them |
| 2026-08-08 | Telegram | auto-watch + hot-reload chat_id |
| 2026-08-10 13:06 | First trade | Fixed symbol format mismatch (synthetic vs scan loop) — 2 iron condors placed, 8 fills |
| 2026-08-10 14:00 | Production v2 | LLM judge (MiniMax), smart exits, voice alerts, charts, 5 new strategies, variable risk, macro calendar |
| 2026-08-10 14:30 | v3.1-v3.3 | Fixed bugs (timezone UnboundLocal, order.side str/enum, position cap bypass on restart) |
| 2026-08-10 14:50 | Intel layer | OI analytics, GEX, max-pain, performance attribution, alpha decay, auto-params tuning, reconciliation, trade journal, compliance PDF, multi-broker stub, anomaly detection, Mavis co-pilot |
| 2026-08-10 15:00 | Reconciliation fix | Auto-close excess positions at startup (the qty=150 doubling bug) |
| 2026-08-10 15:35 | GitHub push | 153 files pushed to private repo `SaiNihal2622/kotak-neo-trading-bot` |

---

## 11. File map (the what + where)

```
kotak-neo-bot/
├── README.md                              # this file
├── requirements.txt                        # python deps
├── .gitignore                              # excludes secrets, .venv, logs, data_cache
│
├── config/
│   ├── settings.yaml                       # ALL tunable params
│   ├── credentials.env                     # SECRETS (gitignored)
│   └── credentials.env.template            # template with placeholders
│
├── kotak_bot/                              # main package
│   ├── __main__.py                         # entry point: run_paper() main loop
│   ├── utils/
│   │   ├── clock.py                        # now_ist(), is_market_open(), market_session()
│   │   └── logger.py                       # loguru setup
│   ├── broker/
│   │   ├── base.py                         # abstract BrokerClient + Order/Position/Tick
│   │   ├── paper_client.py                 # PaperClient — virtual book
│   │   └── neo_client.py                   # NeoClient — Kotak Neo v2 wrapper
│   ├── data/
│   │   ├── live_feed.py                    # synthetic + live UAT tick feed
│   │   ├── historical.py                   # yfinance / TrueData / nselib / Dhan
│   │   ├── macro_calendar.py               # 21 RBI/Fed/CPI/Budget events
│   │   └── kotak_research.py               # Kotak daily derivatives PDF crawler
│   ├── signals/
│   │   ├── technical.py                    # 60+ indicators
│   │   ├── regime.py                       # trending/range/volatile classifier
│   │   ├── llm_judge.py                    # MiniMax M2.7-highspeed news judge
│   │   └── signals_news_init.py            # lazy init helpers
│   ├── strategy/
│   │   ├── base.py                         # SignalContext, TradePlan, BaseStrategy
│   │   ├── selector.py                     # regime-based strategy picker
│   │   ├── directional.py                  # DirectionalDebit
│   │   ├── premium_selling.py              # IronCondor, ShortStrangle
│   │   ├── event_play.py                   # EventStraddle
│   │   └── advanced.py                     # 8 more strategies
│   ├── risk/
│   │   └── engine.py                       # 3-preset variable risk
│   ├── execution/
│   │   ├── order_manager.py                # TradePlan → broker orders
│   │   └── smart_exit.py                   # continuous exit eval + greeks
│   ├── intel/                              # production polish layer
│   │   ├── oi_analytics.py                 # resistance/support/max-pain/PCR/GEX
│   │   ├── performance.py                  # tracker + alpha decay + auto-tune
│   │   ├── reconcile.py                    # broker vs internal diff
│   │   ├── journal.py                      # trade journal + compliance PDF + multi-broker
│   │   └── mark_to_market.py               # P&L + anomaly detector + OI heatmap
│   └── alerts/
│       ├── telegram.py                     # text + voice + chart
│       ├── telegram_commands.py            # 13 commands
│       └── email.py                        # Gmail fallback
│
├── scripts/
│   ├── co_pilot.py                         # Mavis AI advisor (cron every 10 min)
│   └── status.py                           # manual P&L snapshot
│
├── dashboard/
│   └── app.py                              # Streamlit 8-page dashboard on :8501
│
├── backtest/
│   ├── engine.py                           # vectorbt framework
│   └── real_backtest.py                    # backtest on real NIFTY data
│
├── tests/
│   └── test_imports.py
│
├── data_cache/                             # runtime state (gitignored)
│   ├── paper_state.json                    # paper book
│   ├── audit_log.jsonl                     # SEBI audit trail
│   ├── reconcile.jsonl                     # position reconciliation log
│   ├── performance.csv                     # per-strategy metrics
│   ├── ticks.csv                           # tick history
│   ├── voice_alerts/                       # synthesized WAV files
│   ├── charts/                             # daily P&L charts
│   ├── heatmaps/                           # OI heatmaps
│   ├── journal/                            # trade entry/exit screenshots
│   └── compliance/                         # SEBI audit PDFs
│
└── logs/                                   # gitignored
    ├── bot.log
    ├── bot_stderr.log
    ├── trades.csv
    └── signals.csv
```

---

## 12. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Bot starts but no trades fire | `feed.get_ltp(symbol) == 0` | check synthetic feed started, or live UAT WS auth |
| Telegram alerts flood | Reconciliation mismatch | check `data_cache/reconcile.jsonl`, run startup reconcile |
| Position count > 2 | Doubled condors from restart | v3.7+ auto-closes excess at startup |
| `UnboundLocalError: timezone` | `from datetime import X` shadowed module-level import | remove inner import, use module-level |
| `TypeError: place_order() got unexpected keyword 'bracket'` | PaperClient missing kwargs | v3+ PaperClient accepts `bracket=None, cover_sl=None` |
| `cannot access local variable 'MAX_OPEN_POSITIONS'` | var assigned after use in inner block | assign before inner block, or use local var inline |
| Co-pilot WinError 5 on read | Bot writing paper_state.json while co-pilot reads | v3.6+ retry with O_RDONLY share mode + 3x retry |
| `str object has no attribute 'value'` | Order.side loaded as string from JSON | check `hasattr(o.side, 'value')` first |

---

## 13. Future work

- [ ] Live UAT websocket tick delivery (subscribe with proper exchange segment + scrip token discovery for option chain)
- [ ] Real account deployment (static IP, SEBI Algo ID, small capital)
- [ ] Dhan integration for real 1-min historical + option chain Greeks
- [ ] Multi-broker arbitrage (route orders to cheapest of Kotak/Dhan/Upstox)
- [ ] Dashboard upgrade with OI heatmap page + Greeks page + performance page
- [ ] Slack/Discord alert channels (in addition to Telegram)
- [ ] Position sizing based on Kelly criterion
- [ ] Walk-forward optimization on real intraday data
- [ ] IV surface fitting (Black-76 with term structure)
- [ ] Cross-asset signals (USDINR, crude, US 10Y) to bias direction

---

## 14. License & contact

Personal project. No warranty. Trading involves risk of loss.

Author: Sai Nihal Boora · `sainihalboora@gmail.com` · @SaiNihal2622 on GitHub
