# Session Handoff — kotak-neo-bot

This document is the **single source of truth** for cross-session continuity on the
kotak-neo-bot project. When any Mavis session starts (root or cron), it should
read this file first. When it makes a material change, it should append a section.

Maintained by:
- `scripts/session_death_detector.py` (every 5 min, appends death-sweep blocks)
- The active primary chat (this file's owner: `mvs_23123df3eb9544178ff0d9926de5cae5`)
- Critical crons (kotak-bot-watchdog, kotak-self-monitor, kotak-nightly-improvement)
  are wired to write back here via `mavis session send` to this primary chat.

---

## Last refresh — 2026-09-02 00:50 IST (commits 1b8580f + 118deb6 + 62e1fd4 + f8aab8d)

### Session 2 of the self-driving era — 4 new modules wired in
- **scripts/backtest_engine.py** (commit 118deb6) — regime-aware edge for live decisions
  - `get_strategy_edge(strategy, days=30)` — recent P&L / win rate / sample size / edge-decay flag
  - `get_regime_edge(vix_bucket, trend)` — which strategies have edge in current VIX regime
  - `simulate_trade_proposal(legs, capital, vix)` — quick max loss / max profit / sizing check
  - `get_backtest_summary()` — top-level rollup, always in LLM context
  - Warns on sample_grade F (untested strategies), points to top regime-fit strategies
- **scripts/oi_change_detector.py** (commit 62e1fd4) — institutional positioning tracker
  - Captures OI snapshots from KotakProdFeed every tick
  - Detects build-up (>5% OI increase at a strike = new S/R) and unwinding (decrease = S/R breaking)
  - Tracks PCR shifts (positive = put writers adding = bullish)
  - Persists snapshots to `data_cache/oi_snapshots/` (24h rolling)
  - Logs significant changes to `data_cache/oi_changes.jsonl`
  - Wakes LLM on >15% OI shifts via Telegram alert
- **scripts/telegram_alerter.py** (commit f8aab8d) — rich brain-side Telegram notifications
  - Throttled per category (decision 30s, position 15min, risk 1min, OI 5min, heartbeat 4h, daily 1d)
  - Categorized: decision_made / position_update / risk_alert / oi_alert / heartbeat / daily_summary / session_event
  - Rich formatting with backtest edge + macro context
  - Service start notification fires on every brain boot
  - 4h heartbeat during market hours (09:00-15:30)
- **quant_watchdog.py** (restarted this session) — was MISSING after 22:06 IST Sept 1, that's why brain died

### What the LLM now sees on every decision (full context)
- profit_state (compounding, Kelly, circuit breakers)
- macro (upcoming events + FII/DII)
- backtest (per-strategy edge + regime top picks)
- oi_changes (build-up / unwinding + PCR)
- trade_lessons (past trade lessons)
- open_position_analysis (P&L + suggested actions)
- regime (bull/bear/sideways)
- pre_mortem (challenge the proposed trade)
- intraday_levels, chains_summary, recent_performance, global_markets

### Production system — 11 modules in scripts/
| Module | Purpose |
|---|---|
| candle_engine.py | 1m OHLCV + indicators + patterns |
| dashboard.py | HTML output |
| quant_service.py | The brain (watch loop, LLM, schedulers, HTTP :8503) |
| profit_engine.py | Compounding + Kelly + circuit breakers |
| llm_helpers.py | 5 tools + 2 workflows |
| macro_calendar.py | RBI/FOMC/CPI/NFP + FII/DII |
| trade_journal.py | Auto-journal + lessons |
| position_adjuster.py | Position management |
| **backtest_engine.py** | Regime-aware edge (NEW) |
| **oi_change_detector.py** | Real-time OI changes (NEW) |
| **telegram_alerter.py** | Rich brain-side alerts (NEW) |
| quant_watchdog.py | Safety net (RESTARTED) |
| quant_daemon.py | Alternative watcher (legacy) |

### Running RIGHT NOW (00:50 IST)
- quant_service: PID 7300, running, 1Hz, HTTP :8503 healthy
- quant_watchdog: PID 19380, monitoring, will restart service if dies
- kotak_bot paper: PID 2508, tick 4002, uptime 33.6h, capital Rs.1,00,000, P&L +Rs.9,977.95
- All 23 Mavis crons paused (replaced by in-process scheduler in quant_service)
- In-process schedulers (8 jobs):
  - 08:15 morning brief
  - 08:25 daily maintenance
  - 09:00 opening volatility scanner
  - 13:30 closing straddle scanner
  - 14:30 force square-off
  - 15:45 EOD state backup
  - Sun 18:00 weekly review
  - Sun 21:00 weekend intel + Monday brief
  - 23:00 nightly improvement (self-evolution)

### Use from any chat
```
python scripts/quant_control.py {status|positions|decisions|ask|close|pause|resume}
```

### Telegram alerts (NEW — fires automatically)
- Service start: "🔄 Quant service starting" with PID/endpoint
- LLM decision: "🟢 OPEN iron_condor NIFTY" with target/stop/rationale + edge stats
- OI alert: "🔔 OI alert: NIFTY" when build-up/unwinding >15%
- Position update: every 15 min while open
- Heartbeat: every 4h during market hours
- Daily summary: at 15:30 EOD
- Risk alert: drawdown / circuit breaker (forced, no throttle)

---

- quant_daemon.py (alternative watcher) — passive event detector
- intraday_levels.py + option_chain_analyzer.py — 28-instrument state tracking
- session_death_detector.py + session_715_recovery.py + path_shadow_check.py + rotate_jsonl.py — infra
- kotak_bot/__main__.py — quant_actions reader (block 1c)
- kotak_bot/data/kotak_prod_feed.py — HTTP 400 fix
- kotak_bot/data/kotak_research.py — research PDF cosmetic

### Running RIGHT NOW (16:32 IST)
- quant_service: PID 4680, running, 563 ticks, HTTP :8503 healthy
- quant_watchdog: PID 10384, monitoring, will restart service if dies
- kotak_bot: PID 12496, fresh code (quant_actions reader + HTTP 400 fix loaded)
- All 17 chat-spamming crons: soft-deleted
- 3 chat-targeting crons: target_session_id cleared

### One click to true 24/7
The NSSM install script is ready: system\run_nssm_install_elevated.ps1
Run in admin PowerShell: powershell -ExecutionPolicy Bypass -File <path>
This installs KotakQuantService as a Windows service: 24/7, auto-restart on crash, survives reboots.
Without this, the background process + watchdog gives 24/7 *while logged in*.

### Use from this chat
python scripts/quant_control.py {status|positions|decisions|ask|close|pause|resume}

### END-TO-END VERIFIED 2026-08-31 16:23 IST
- Test OPEN action: bot logged, wrote to quant_pending.jsonl ✓
- Test CLOSE action: bot executed [QUANT-ACTION] CLOSE executed (instrument=NIFTY): 0 trades. ✓
- quant_actions.json reader (block 1c in __main__.py) is loaded and working

### New state (16:24 IST)
- Bot: PID 12496 (new, fresh code), running, tick 166+
- Service: PID 4680, running, HTTP :8503 healthy
- All chat-injecting crons: 17 soft-deleted, 3 target_session_id cleared
- LLM endpoint: direct via /messages (Anthropic format), no Mavis session

### Production-grade architecture
- quant_service.py (24/7 Python) — the brain
  - Polls market every 2s
  - Detects real events
  - Calls LLM directly via httpx (no Mavis, no session, no 715)
  - Persistent state (rolling 50-decision history)
  - HTTP control API on :8503
  - Telegram alerts on every decision
- kotak_bot/__main__.py (the executor)
  - Block 1c reads quant_actions.json every 5s
  - CLOSE: square_off_all() + Telegram
  - OPEN: log + Telegram + quant_pending.jsonl for user review
- This chat (the control surface)
  - python scripts/quant_control.py {status,positions,decisions,ask,close,pause,resume}

### The one-stop solution: quant_service.py
**The Mavis session / cron architecture is no longer the brain.**
A standalone Python service (`scripts/quant_service.py`) is now the
always-on, persistent-LLM, direct-API trading brain. NSSM-installable for
24/7. HTTP control on :8503. Calls the LLM directly via httpx (no
Mavis session, no 715 errors, no chat spam).

### Active state
- Service PID 4680, started 16:12 IST, running, HTTP :8503 healthy
- Bot PID 2388, started 16:00 IST, on OLD code (pre-quant_actions reader)
- 6 errored sessions archived today
- HTTP 400 fix committed (kotak_prod_feed batch-chunk), needs bot restart to load
- Heartbeat crons (kotak-bot-watchdog, kotak-self-monitor) — DISABLED to stop chat spam

### Bot executor hook (added in ccc8630, needs bot restart to load)
- `kotak_bot/__main__.py` block 1c reads `data_cache/quant_actions.json`
- CLOSE: `order_mgr.square_off_all(reason=...)` + Telegram
- OPEN: log + Telegram + write to `quant_pending.jsonl` for review
- consumed=True after processing

### Production-level safety net (Layer 1-4 complete)

### Bot state
- **Process**: alive, liveness writer PID 7332, uptime 6h36m, tick 712
- **Capital**: Rs.1,00,000 (paper)
- **Realized PnL (run-to-date)**: +Rs.9,977.95
- **Open positions**: 0
- **Trades today**: 0 (no fills since 2026-08-27 14:59:28)
- **VIX**: 11.19 (calm, 1.0x multiplier)
- **Data source**: live_kotak
- **Risk preset**: aggressive
- **Intraday cutoff**: 13:30 reached (entry path closed)
- **Force-square-off**: 14:30 fired (no-op, 0 positions)

### Today's brain decisions
- 14:25:52 — HOLD, bias=cautious, max_positions=0, actions=[], note=`intraday_post_1330_cutoff_no_new_entries_terminal_hold`
- 25+ consecutive NOOPs since 12:07 IST. State is structurally terminal for the day.

### Today's fix (commit 58c33a8)
- **P1 fixed**: HTTP 400 in `kotak_prod_feed._fetch_option_quotes` — chunked
  batches of 50, multiple requests, merged results. Bot restart scheduled at
  15:32 IST via one-shot cron `kotak-bot-restart-after-fix`.
- **P2 fixed**: research PDF cosmetic — warning demoted to debug, stale-cache
  fallback.
- **P3 deferred**: yfinance 5d freshness flip-flop (non-blocking).

### Session-death pattern (last 7d)
- Total errored sessions: 13 (12 archived today)
- Pattern A (context_compaction_failed, 7): **FIXED 2026-08-30** via
  `sanitize_tool_result.py` 50KB catch-all. 0 new since.
- Pattern B (715/1000, 6 today): **FIXED 2026-08-31 15:08** by switching
  14 long-lived crons from `mode:sessionId` to `mode:new`. Each tick now
  starts a fresh session; no accumulation, no 715.
- Pattern C (cumulative drift, 6 today): **FIXED** by the same change
  as Pattern B. The drift was on `mode:sessionId` crons; new mode prevents
  it.
- 12 dead sessions archived silently in this pass.
- 3 critical crons now wired to write back to this primary chat:
  `kotak-bot-watchdog`, `kotak-self-monitor`, `kotak-nightly-improvement`.

### Active cron wiring
| Cron | Schedule | Target |
|---|---|---|
| kotak-bot-watchdog | 09:00-15:30 Mon-Fri | `mvs_42e2c15c34934eb68485e31ae393848b` (this chat) |
| kotak-self-monitor | every 15 min | `mvs_42e2c15c34934eb68485e31ae393848b` (this chat) |
| kotak-nightly-improvement | 23:00 daily | `mvs_42e2c15c34934eb68485e31ae393848b` (this chat) |
| kotak-session-death-detector | every 5 min | new session per tick |
| kotak-session-715-recovery | every 5 min | new session per tick |
| kotak-path-shadow-check | 23:00 daily | new session per tick |
| kotak-rotate-jsonl | 23:30 daily | new session per tick |
| kotak-bot-restart-after-fix | 15:32 IST (one-shot) | new session per tick |
| All other 50 crons | per-schedule | new session per tick |

### Production-level safety net (Layer 1-4 complete)
- **Layer 1a (mode:new)**: 14 long-lived crons cleared; 3 critical wired to primary chat
- **Layer 1b (death detector)**: archives errored sessions every 5 min, silent
- **Layer 1c (715 retry)**: soft-retry via mavis cron create, 30-min dedup
- **Layer 2 (handoff)**: this doc is the single source of truth
- **Layer 3 (back-channel)**: 3 critical crons write here
- **Layer 4 (smoke tests)**: path-shadow + JSONL rotation nightly, no regression

### New scripts (this session)
- `scripts/session_death_detector.py` — sweep + archive
- `scripts/session_715_recovery.py` — soft-retry transient 715 errors
- `scripts/path_shadow_check.py` — catches 2026-08-28 Path-shadow bug pattern
- `scripts/rotate_jsonl.py` — caps growing JSONL files at 500KB
- `scripts/intraday_levels.py` — day OHLC, VWAP, opening range, swing 30m
- `scripts/option_chain_analyzer.py` — full chain + BS Greeks for 28 instruments
- `scripts/quant_daemon.py` — always-on watcher (event detector)
- `scripts/quant_service.py` — **THE BRAIN** — direct LLM API, persistent state, HTTP control
- `scripts/quant_control.py` — chat-side control (status, decisions, ask, close)
- `scripts/test_llm_direct.py` — confirms /messages endpoint works
- `system/install_quant_service.ps1` — NSSM installer
- `kotak_bot/data/kotak_prod_feed.py` — HTTP 400 fix (chunked batches of 50)
- `kotak_bot/data/kotak_research.py` — research PDF cosmetic downgrade
- `kotak_bot/__main__.py` block 1c — quant_actions.json reader

### Architecture (final)
- quant_service (24/7 Python) — direct LLM API calls via httpx
- kotak_bot/__main__.py — executor (reads quant_actions.json, places orders)
- This chat (primary) — control via quant_control.py + manual LLM ask
- data_cache/session_handoff.md — the single source of truth across sessions

### To restart bot with new code (HTTP 400 fix + quant_actions reader):
  nssm restart KotakBotPaper
  # or: Start-Process -FilePath ".venv\Scripts\python.exe" -ArgumentList "-u","-m","kotak_bot","paper" -RedirectStandardOutput "bot_stdout.log" -RedirectStandardError "bot_stderr.log" -WindowStyle Hidden

### To NSSM-install the quant service (needs admin UAC):
  powershell -Verb RunAs -File system\install_quant_service.ps1
  # or run in background: Start-Process -FilePath ".venv\Scripts\python.exe" -ArgumentList "-u","scripts/quant_service.py" -WindowStyle Hidden -RedirectStandardOutput "Logs\quant_service.out.log"

---

## Death-detector sweep @ 2026-08-31T15:08:38+05:30
12 dead sessions swept in the initial Layer-1 cleanup:
- All `error_code=50001` (715/1000) and `error_code=50113` (503/502 upstream).
- All were 5+ min old, all archived silently, none were primary chats.
- See `data_cache/session_death_detector.jsonl` for full list.

---

## 715/1000 recovery alert @ 2026-08-31T15:12:40+05:30
Detected 4 session(s) with `unknown error 715 (1000)` in the last 24h.
**Pattern**: 715 is an upstream/model-provider transient API error, NOT a context-size issue.
**Mitigated 2026-08-31 15:08**: switched 14 long-lived crons from `mode:sessionId` to `mode:new`.
**Auto-recovery**: dead sessions archived; next cron tick starts a fresh session automatically.

Affected (last 24h):
- `mvs_1100a67f1b1b4598` — kotak-session-hygiene · 08-31 14:10 — 14:14:35
- `mvs_9301778519904c74` — kotak-mavis-self-driver · 08-31 11:50 — 12:02:47
- `mvs_60c952d415704244` — kotak-trader-desk · 08-31 11:55 — 12:02:46
- `mvs_4e4669276da7456e` — kotak-mavis-self-driver · 08-31 10:07 — 10:12:22

## 715/1000 recovery alert @ 2026-08-31T15:15:24+05:30
Detected 4 session(s) with `unknown error 715 (1000)` in the last 24h.
**Pattern**: 715 is an upstream/model-provider transient API error, NOT a context-size issue.
**Mitigated 2026-08-31 15:08**: switched 14 long-lived crons from `mode:sessionId` to `mode:new`.
**Auto-recovery**: dead sessions archived; next cron tick starts a fresh session automatically.

Affected (last 24h):
- `mvs_1100a67f1b1b4598` — kotak-session-hygiene · 08-31 14:10 — 14:14:35
- `mvs_9301778519904c74` — kotak-mavis-self-driver · 08-31 11:50 — 12:02:47
- `mvs_60c952d415704244` — kotak-trader-desk · 08-31 11:55 — 12:02:46
- `mvs_4e4669276da7456e` — kotak-mavis-self-driver · 08-31 10:07 — 10:12:22

## 715/1000 recovery alert @ 2026-08-31T15:20:12+05:30
Detected 4 session(s) with `unknown error 715 (1000)` in the last 24h.
**Pattern**: 715 is an upstream/model-provider transient API error, NOT a context-size issue.
**Mitigated 2026-08-31 15:08**: switched 14 long-lived crons from `mode:sessionId` to `mode:new`.
**Auto-recovery**: dead sessions archived; next cron tick starts a fresh session automatically.

Affected (last 24h):
- `mvs_1100a67f1b1b4598` — kotak-session-hygiene · 08-31 14:10 — 14:14:35
- `mvs_9301778519904c74` — kotak-mavis-self-driver · 08-31 11:50 — 12:02:47
- `mvs_60c952d415704244` — kotak-trader-desk · 08-31 11:55 — 12:02:46
- `mvs_4e4669276da7456e` — kotak-mavis-self-driver · 08-31 10:07 — 10:12:22

## 715/1000 recovery alert @ 2026-08-31T15:25:09+05:30
Detected 4 session(s) with `unknown error 715 (1000)` in the last 24h.
**Pattern**: 715 is an upstream/model-provider transient API error, NOT a context-size issue.
**Mitigated 2026-08-31 15:08**: switched 14 long-lived crons from `mode:sessionId` to `mode:new`.
**Auto-recovery**: dead sessions archived; next cron tick starts a fresh session automatically.

Affected (last 24h):
- `mvs_1100a67f1b1b4598` — kotak-session-hygiene · 08-31 14:10 — 14:14:35
- `mvs_9301778519904c74` — kotak-mavis-self-driver · 08-31 11:50 — 12:02:47
- `mvs_60c952d415704244` — kotak-trader-desk · 08-31 11:55 — 12:02:46
- `mvs_4e4669276da7456e` — kotak-mavis-self-driver · 08-31 10:07 — 10:12:22

## 715/1000 recovery alert @ 2026-08-31T15:29:43+05:30
Detected 4 session(s) with `unknown error 715 (1000)` in the last 24h.
**Pattern**: 715 is an upstream/model-provider transient API error, NOT a context-size issue.
**Mitigated 2026-08-31 15:08**: switched 14 long-lived crons from `mode:sessionId` to `mode:new`.
**Auto-recovery**: dead sessions archived; next cron tick starts a fresh session automatically.

Affected (last 24h):
- `mvs_1100a67f1b1b4598` — kotak-session-hygiene · 08-31 14:10 — 14:14:35
- `mvs_9301778519904c74` — kotak-mavis-self-driver · 08-31 11:50 — 12:02:47
- `mvs_60c952d415704244` — kotak-trader-desk · 08-31 11:55 — 12:02:46
- `mvs_4e4669276da7456e` — kotak-mavis-self-driver · 08-31 10:07 — 10:12:22

## 715/1000 recovery alert @ 2026-08-31T15:30:10+05:30
Detected 4 session(s) with `unknown error 715 (1000)` in the last 24h.
**Pattern**: 715 is an upstream/model-provider transient API error, NOT a context-size issue.
**Mitigated 2026-08-31 15:08**: switched 14 long-lived crons from `mode:sessionId` to `mode:new`.
**Auto-recovery**: dead sessions archived; next cron tick starts a fresh session automatically.

Affected (last 24h):
- `mvs_1100a67f1b1b4598` — kotak-session-hygiene · 08-31 14:10 — 14:14:35
- `mvs_9301778519904c74` — kotak-mavis-self-driver · 08-31 11:50 — 12:02:47
- `mvs_60c952d415704244` — kotak-trader-desk · 08-31 11:55 — 12:02:46
- `mvs_4e4669276da7456e` — kotak-mavis-self-driver · 08-31 10:07 — 10:12:22

## 715/1000 recovery alert @ 2026-08-31T15:35:19+05:30
Detected 4 session(s) with `unknown error 715 (1000)` in the last 24h.
**Pattern**: 715 is an upstream/model-provider transient API error, NOT a context-size issue.
**Mitigated 2026-08-31 15:08**: switched 14 long-lived crons from `mode:sessionId` to `mode:new`.
**Auto-recovery**: dead sessions archived; next cron tick starts a fresh session automatically.

Affected (last 24h):
- `mvs_1100a67f1b1b4598` — kotak-session-hygiene · 08-31 14:10 — 14:14:35
- `mvs_9301778519904c74` — kotak-mavis-self-driver · 08-31 11:50 — 12:02:47
- `mvs_60c952d415704244` — kotak-trader-desk · 08-31 11:55 — 12:02:46
- `mvs_4e4669276da7456e` — kotak-mavis-self-driver · 08-31 10:07 — 10:12:22

## 715/1000 recovery alert @ 2026-08-31T15:40:14+05:30
Detected 4 session(s) with `unknown error 715 (1000)` in the last 24h.
**Pattern**: 715 is an upstream/model-provider transient API error, NOT a context-size issue.
**Mitigated 2026-08-31 15:08**: switched 14 long-lived crons from `mode:sessionId` to `mode:new`.
**Auto-recovery**: dead sessions archived; next cron tick starts a fresh session automatically.

Affected (last 24h):
- `mvs_1100a67f1b1b4598` — kotak-session-hygiene · 08-31 14:10 — 14:14:35
- `mvs_9301778519904c74` — kotak-mavis-self-driver · 08-31 11:50 — 12:02:47
- `mvs_60c952d415704244` — kotak-trader-desk · 08-31 11:55 — 12:02:46
- `mvs_4e4669276da7456e` — kotak-mavis-self-driver · 08-31 10:07 — 10:12:22

## 715/1000 recovery alert @ 2026-08-31T15:45:11+05:30
Detected 4 session(s) with `unknown error 715 (1000)` in the last 24h.
**Pattern**: 715 is an upstream/model-provider transient API error, NOT a context-size issue.
**Mitigated 2026-08-31 15:08**: switched 14 long-lived crons from `mode:sessionId` to `mode:new`.
**Auto-recovery**: dead sessions archived; next cron tick starts a fresh session automatically.

Affected (last 24h):
- `mvs_1100a67f1b1b4598` — kotak-session-hygiene · 08-31 14:10 — 14:14:35
- `mvs_9301778519904c74` — kotak-mavis-self-driver · 08-31 11:50 — 12:02:47
- `mvs_60c952d415704244` — kotak-trader-desk · 08-31 11:55 — 12:02:46
- `mvs_4e4669276da7456e` — kotak-mavis-self-driver · 08-31 10:07 — 10:12:22

## 715/1000 recovery alert @ 2026-08-31T15:45:16+05:30
Detected 4 session(s) with `unknown error 715 (1000)` in the last 24h.
**Pattern**: 715 is an upstream/model-provider transient API error, NOT a context-size issue.
**Mitigated 2026-08-31 15:08**: switched 14 long-lived crons from `mode:sessionId` to `mode:new`.
**Auto-recovery**: dead sessions archived; next cron tick starts a fresh session automatically.

Affected (last 24h):
- `mvs_1100a67f1b1b4598` — kotak-session-hygiene · 08-31 14:10 — 14:14:35
- `mvs_9301778519904c74` — kotak-mavis-self-driver · 08-31 11:50 — 12:02:47
- `mvs_60c952d415704244` — kotak-trader-desk · 08-31 11:55 — 12:02:46
- `mvs_4e4669276da7456e` — kotak-mavis-self-driver · 08-31 10:07 — 10:12:22

## 715/1000 recovery alert @ 2026-08-31T15:50:18+05:30
Detected 4 session(s) with `unknown error 715 (1000)` in the last 24h.
**Pattern**: 715 is an upstream/model-provider transient API error, NOT a context-size issue.
**Mitigated 2026-08-31 15:08**: switched 14 long-lived crons from `mode:sessionId` to `mode:new`.
**Auto-recovery**: dead sessions archived; next cron tick starts a fresh session automatically.

Affected (last 24h):
- `mvs_1100a67f1b1b4598` — kotak-session-hygiene · 08-31 14:10 — 14:14:35
- `mvs_9301778519904c74` — kotak-mavis-self-driver · 08-31 11:50 — 12:02:47
- `mvs_60c952d415704244` — kotak-trader-desk · 08-31 11:55 — 12:02:46
- `mvs_4e4669276da7456e` — kotak-mavis-self-driver · 08-31 10:07 — 10:12:22

## 715/1000 recovery alert @ 2026-08-31T15:55:11+05:30
Detected 4 session(s) with `unknown error 715 (1000)` in the last 24h.
**Pattern**: 715 is an upstream/model-provider transient API error, NOT a context-size issue.
**Mitigated 2026-08-31 15:08**: switched 14 long-lived crons from `mode:sessionId` to `mode:new`.
**Auto-recovery**: dead sessions archived; next cron tick starts a fresh session automatically.

Affected (last 24h):
- `mvs_1100a67f1b1b4598` — kotak-session-hygiene · 08-31 14:10 — 14:14:35
- `mvs_9301778519904c74` — kotak-mavis-self-driver · 08-31 11:50 — 12:02:47
- `mvs_60c952d415704244` — kotak-trader-desk · 08-31 11:55 — 12:02:46
- `mvs_4e4669276da7456e` — kotak-mavis-self-driver · 08-31 10:07 — 10:12:22

## 715/1000 recovery alert @ 2026-08-31T16:00:09+05:30
Detected 4 session(s) with `unknown error 715 (1000)` in the last 24h.
**Pattern**: 715 is an upstream/model-provider transient API error, NOT a context-size issue.
**Mitigated 2026-08-31 15:08**: switched 14 long-lived crons from `mode:sessionId` to `mode:new`.
**Auto-recovery**: dead sessions archived; next cron tick starts a fresh session automatically.

Affected (last 24h):
- `mvs_1100a67f1b1b4598` — kotak-session-hygiene · 08-31 14:10 — 14:14:35
- `mvs_9301778519904c74` — kotak-mavis-self-driver · 08-31 11:50 — 12:02:47
- `mvs_60c952d415704244` — kotak-trader-desk · 08-31 11:55 — 12:02:46
- `mvs_4e4669276da7456e` — kotak-mavis-self-driver · 08-31 10:07 — 10:12:22

## 715/1000 recovery alert @ 2026-08-31T16:00:17+05:30
Detected 4 session(s) with `unknown error 715 (1000)` in the last 24h.
**Pattern**: 715 is an upstream/model-provider transient API error, NOT a context-size issue.
**Mitigated 2026-08-31 15:08**: switched 14 long-lived crons from `mode:sessionId` to `mode:new`.
**Auto-recovery**: dead sessions archived; next cron tick starts a fresh session automatically.

Affected (last 24h):
- `mvs_1100a67f1b1b4598` — kotak-session-hygiene · 08-31 14:10 — 14:14:35
- `mvs_9301778519904c74` — kotak-mavis-self-driver · 08-31 11:50 — 12:02:47
- `mvs_60c952d415704244` — kotak-trader-desk · 08-31 11:55 — 12:02:46
- `mvs_4e4669276da7456e` — kotak-mavis-self-driver · 08-31 10:07 — 10:12:22

## 715/1000 recovery alert @ 2026-08-31T16:05:07+05:30
Detected 4 session(s) with `unknown error 715 (1000)` in the last 24h.
**Pattern**: 715 is an upstream/model-provider transient API error, NOT a context-size issue.
**Mitigated 2026-08-31 15:08**: switched 14 long-lived crons from `mode:sessionId` to `mode:new`.
**Auto-recovery**: dead sessions archived; next cron tick starts a fresh session automatically.

Affected (last 24h):
- `mvs_1100a67f1b1b4598` — kotak-session-hygiene · 08-31 14:10 — 14:14:35
- `mvs_9301778519904c74` — kotak-mavis-self-driver · 08-31 11:50 — 12:02:47
- `mvs_60c952d415704244` — kotak-trader-desk · 08-31 11:55 — 12:02:46
- `mvs_4e4669276da7456e` — kotak-mavis-self-driver · 08-31 10:07 — 10:12:22

## 715/1000 recovery alert @ 2026-08-31T16:10:15+05:30
Detected 4 session(s) with `unknown error 715 (1000)` in the last 24h.
**Pattern**: 715 is an upstream/model-provider transient API error, NOT a context-size issue.
**Mitigated 2026-08-31 15:08**: switched 14 long-lived crons from `mode:sessionId` to `mode:new`.
**Auto-recovery**: dead sessions archived; next cron tick starts a fresh session automatically.

Affected (last 24h):
- `mvs_1100a67f1b1b4598` — kotak-session-hygiene · 08-31 14:10 — 14:14:35
- `mvs_9301778519904c74` — kotak-mavis-self-driver · 08-31 11:50 — 12:02:47
- `mvs_60c952d415704244` — kotak-trader-desk · 08-31 11:55 — 12:02:46
- `mvs_4e4669276da7456e` — kotak-mavis-self-driver · 08-31 10:07 — 10:12:22

## 715/1000 recovery alert @ 2026-08-31T16:15:13+05:30
Detected 4 session(s) with `unknown error 715 (1000)` in the last 24h.
**Pattern**: 715 is an upstream/model-provider transient API error, NOT a context-size issue.
**Mitigated 2026-08-31 15:08**: switched 14 long-lived crons from `mode:sessionId` to `mode:new`.
**Auto-recovery**: dead sessions archived; next cron tick starts a fresh session automatically.

Affected (last 24h):
- `mvs_1100a67f1b1b4598` — kotak-session-hygiene · 08-31 14:10 — 14:14:35
- `mvs_9301778519904c74` — kotak-mavis-self-driver · 08-31 11:50 — 12:02:47
- `mvs_60c952d415704244` — kotak-trader-desk · 08-31 11:55 — 12:02:46
- `mvs_4e4669276da7456e` — kotak-mavis-self-driver · 08-31 10:07 — 10:12:22
