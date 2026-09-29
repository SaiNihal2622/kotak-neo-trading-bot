# Session Handoff — 2026-09-29 14:55 IST

## TL;DR

User asked **"fix all"** the 3 issues from today's broken-condor incident.
All 3 fixes shipped in 3 commits, tests added, bot restarted, positions closed, all working.

## Commits shipped this session

```
2bc149b fix(bot): wire feed.set_broker() after start for late-binding tick replay
acbcf95 fix(live-feed): wire PaperClient broker injection + late-binding setter
e0051c6 fix(operational): broken-condor detector + emergency close + CLOSE_ALL orphan fix
```

## The broken-condor incident (recap)

Today's -Rs.10,720 paper loss happened because:

1. **Bot thought it had an iron condor** (4 legs), but only the BUY (wing) legs executed (50 BUYs, 0 SELLs). The bot kept averaging down its longs as NIFTY dropped.
2. **SELL LIMIT auto-snap couldn't fire** because PaperClient had 0 ticks. LLM kept proposing limit=113.0 while bid=12.0; without bid data, snap couldn't bring the limit down.
3. **CLOSE_ALL orphan fallback was a no-op** because the trigger condition (`if order_mgr had 0 trades`) was wrong — order_mgr had 2 trades from brain-driven OPENs.

## Fixes shipped

### Fix A: Wire KotakProdFeed ticks → PaperClient (`live_feed.py`)

- `set_broker(broker)` — late-binding setter that replays cached ticks to the new broker (in case order-of-ops meant broker wasn't ready at construction)
- Defensive `_dispatch` logging one-time warning if broker is None
- `__main__.py`: explicit `feed.set_broker(broker)` after `feed.start()` so the wiring is bulletproof

### Fix B: CLOSE_ALL orphan fallback always runs (`__main__.py`)

- Changed `if n == 0:` (only close orphans if order_mgr was empty) to `if True:` (always close broker orphans)
- Comment explains why: brain-driven OPENs bypass order_mgr entirely

### Fix C: Detect broken-condor state + emergency close (`__main__.py`)

- After each QUANT-ACTION OPEN, check `_placed > 0 and _placed < len(_qa_legs)` for multi-leg strategies
- If partial: write `_broken_condor.json` with the orphan BUY legs
- Top-of-loop handler reads the marker and closes orphan longs at MARKET
- Marked consumed after cleanup

## End-to-end verification

| Time | Event | Outcome |
|---|---|---|
| 14:19:46 | Bot restarted (PID 1736) | New code loaded |
| 14:24:49 | `_broken_condor.json` processed | 4 PAPER SELL MARKET orders fired, all filled |
| 14:25 | Positions: 0 | Bleeding stopped |
| 14:48:05 | Bot restarted again (PID 21112) | Fix A loaded |
| 14:48:11 | `[LIVE-FEED] broker set late; replayed 0 cached ticks to PaperClient` | Fix A confirmed working |
| 14:51 | `tick_count=152` | Ticks flowing through `_dispatch` → `inject_tick` |

## Test coverage added

- `tests/test_broken_condor_fix.py` — 5 tests for Fixes B + C
- `tests/test_live_feed_paper_wiring.py` — 5 tests for Fix A

**Total: 10 new tests, all passing.** Full suite: 711 passing (3 pre-existing flaky/unrelated failures excluded).

## Current state

- **Bot PID**: 21112, uptime 7+ minutes, healthy
- **Cash**: Rs.89,280
- **Realized P&L today**: -Rs.10,720 (broken-condor loss locked in)
- **Open positions**: 0
- **Brain PID**: 16112, healthy on :8503
- **CAS strategies**: loaded, will fire when ADX>25 + session conditions met
- **All fixes verified live**

## What I did NOT do

- Did not investigate why the bot kept ADDING to losers (50 BUYs over the day). This may be a separate issue — the brain's SixJudgments path was firing iron_condor_nifty every 10s and each iteration was adding more BUYs to existing positions. The dedup guard at line ~1940 prevents duplicate `NIFTY01OCT2622550CE` entries, but doesn't prevent ADDING to a different strike like `NIFTY01OCT2622850CE`.
- Did not investigate why the brain keeps proposing limit=113.0 (the SixJudgments LLM prompt may need calibration, or the live data feed it sees has bad limit values).
- Did not pre-empt the next broken-condor by detecting when the bot tries to BUY a leg whose SELL counterpart hasn't filled in the last 30s. The current detector only fires AFTER a partial fill.

These are followups for next session. Today's immediate damage control is done.

## Recovery

- **Bot dead**: `nssm restart KotakBotPaper` or `Restart-Service KotakBotPaper`
- **Force close all**: write `data_cache/mavis_force_action.json` with `action: CLOSE_ALL`
- **Force close broken-condor**: write `data_cache/_broken_condor.json` with the format in `tests/test_broken_condor_fix.py::TestBrokenCondorDetector::test_broken_condor_marker_format`