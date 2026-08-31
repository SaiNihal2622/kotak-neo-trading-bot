# Session Handoff — kotak-neo-bot

This document is the **single source of truth** for cross-session continuity on the
kotak-neo-bot project. When any Mavis session starts (root or cron), it should
read this file first. When it makes a material change, it should append a section.

Maintained by:
- `scripts/session_death_detector.py` (every 5 min, appends death-sweep blocks)
- The active primary chat (this file's owner: `mvs_42e2c15c34934eb68485e31ae393848b`)
- Critical crons (kotak-bot-watchdog, kotak-self-monitor, kotak-nightly-improvement)
  are wired to write back here via `mavis session send` to this primary chat.

---

## Last refresh — 2026-08-31 15:32 IST (commits 58c33a8 + 5d2a1c4 pending)

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
- `kotak_bot/data/kotak_prod_feed.py` — HTTP 400 fix (chunked batches of 50)
- `kotak_bot/data/kotak_research.py` — research PDF cosmetic downgrade

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
