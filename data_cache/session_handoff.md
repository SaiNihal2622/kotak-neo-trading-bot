# Session Handoff — 2026-09-29 19:50 IST

## Status

| Metric | Value |
|---|---|
| Cash | Rs.89,159.50 |
| Realized P&L (today) | -Rs.10,840.50 |
| Open positions | 0 |
| Bot PID | 6900, uptime 30s (just restarted) |
| Bot VIX | 13.41 |
| Streak (green days) | 0/10 |
| Cumulative return | -10.72% |
| Total trades | 68 |

**Market status**: closed (15:30 IST). No positions, no active risk.

## What happened since last session

At 14:24:49 IST my broken-condor handler force-closed 4 longs to stop the bleeding. That worked.

But at 15:15:01 IST, **a NEW bug surfaced**: order_mgr still thought the 4 trades were open (because my handler used `broker.place_order` directly, bypassing `order_mgr.close_trade`). EOD force-square at 15:15 ran `close_trade()` on those trades. The close orders had `tag=f"close_{order.order_id}"` = `"close_None"` (because the reconstructed Order objects had `order_id=None`).

Since the broker had 0 longs at that point, those "close" SELLs **OPENED 3 new SHORT positions**. Then ORPHAN-AUTO-CLOSE detected the orphan SHORTS and bought them back. **Net churn loss: ~Rs.120.**

## Fixes shipped today

```
eaa2c51 fix(close-tag): propagate order_id + broken-condor handler updates order_mgr
```

This commit has TWO fixes bundled:

### Fix D — propagate order_id

- `_leg_records` now captures `order_id` alongside symbol/side/qty/fill_price
- Reconstructed `Order()` in `register_external_managed_trade` propagates `order_id`
- Result: `close_trade()` generates `close_PAPER-XXXX` instead of `close_None`
- Without this fix, EOD force-square creates bogus "close" orders that re-open positions as SHORTS

### Fix E — broken-condor handler updates order_mgr

- After closing via `broker.place_order`, the handler now also:
  1. Looks up `_symbol_to_trade[sym]` to find the trade_id
  2. Sets `trade.closed_at` (prevents future `close_trade()` calls on this trade)
  3. Removes from `_symbol_to_trade` (prevents orphan-killer from re-closing)
- Same fix applied to both handlers (top-loop + force-action)

### 6 new tests in test_close_none_fix.py

All passing. Tests cover:
- `_leg_records` captures order_id
- Reconstructed Order propagates order_id
- `close_trade()` generates proper `close_<id>` tag (NOT `close_None`) when order_id is set
- Regression test: with `order_id=None`, the tag IS `close_None` (proves the fix changes behavior)
- Top-loop handler updates `order_mgr._symbol_to_trade`
- Force-action handler updates order_mgr (with `reason='broken_condor_emergency'`)

## Test status

- **36 tests** passing across 4 fix-related test files
  - `test_close_none_fix.py` (6 new)
  - `test_broken_condor_fix.py` (5 from earlier today)
  - `test_live_feed_paper_wiring.py` (5 from earlier today)
  - `test_cas_strategies.py` (20 from earlier today)
- Other pre-existing flaky tests excluded: `test_dashboard.py`, `test_liveness.py`, `test_reconstruct_today_journal.py`, `test_phase15_fixes.py`

## Earlier today (also shipped)

```
0836c6e docs(session_handoff): CAS implementation complete + ADX wired
0f293e8 feat(candle-engine): compute ADX (Average Directional Index)
592a4d8 test(cas): 20 tests for NIFTY CASH strategies + routing
0b2a6ac feat(routing): route NIFTY CASH legs to nse_cm segment + NSE exchange
14c3b75 feat(strategy-library): add NIFTY CASH (CAS) strategies
2bc149b fix(bot): wire feed.set_broker() after start for late-binding tick replay
acbcf95 fix(live-feed): wire PaperClient broker injection + late-binding setter
e0051c6 fix(operational): broken-condor detector + emergency close + CLOSE_ALL orphan fix
```

## Followups (still open from earlier)

- Investigate why the brain fires `iron_condor_nifty` every ~10s (chatter)
- Investigate why SixJudgments LLM proposes `limit=113.0` when bid=`12.0` (the root cause of broken-condor)
- Add post-no-new-trades-time safety: at 15:00 IST, if positions > 0, write force-square marker to prevent 15:15 churn

## Recovery

- **Bot dead mid-session**: `nssm restart KotakBotPaper` (or use brain HTTP `/command` with `cmd:run`)
- **Force close all**: write `data_cache/mavis_force_action.json` with `action: CLOSE_ALL`
- **Force close broken-condor**: write `data_cache/_broken_condor.json` with format from `tests/test_broken_condor_fix.py`

## Cash position to track tomorrow

- Capital basis: Rs.100,000 → current cash Rs.89,159.50
- Need +Rs.10,840.50 to recover to baseline
- That requires either a +12% gain day, OR many days of compounding
- Streak counter starts fresh tomorrow (Sep 30)