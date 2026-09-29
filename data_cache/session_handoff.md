# Session Handoff — 2026-09-29 13:55 IST

## What was done this session

User asked to **"implement CAS too, i heard that we get so much profits and make better"** — add
NIFTY CASH (CAS, spot) trading alongside the existing options strategies.

### Commits shipped (4 total)

```
0f293e8 feat(candle-engine): compute ADX (Average Directional Index)
592a4d8 test(cas): 20 tests for NIFTY CASH strategies + routing
0b2a6ac feat(routing): route NIFTY CASH legs to nse_cm segment + NSE exchange
14c3b75 feat(strategy-library): add NIFTY CASH (CAS) strategies — nifty_cash_long + nifty_cash_short
```

### What got built

**1. CAS strategies** (`scripts/strategy_library.py`)
- `nifty_cash_long`: ADX>25 + RSI>55 + session_pct>+0.3% → BUY NIFTY cash, target +1.0%, stop -0.75%
- `nifty_cash_short`: mirror for short side
- Conservative: 1 lot max (75 shares NIFTY), even if `vol_targeted_size()` says more
- Hard cap enforced in `generate_trade_plan` via `cash_lots = max(1, min(n_lots, 1))`
- Entry window 9:45-14:30 IST (avoid opening noise)
- max_hold 240 minutes (4h intraday MIS, mandatory EOD square-off)

**2. CAS routing** (`kotak_bot/__main__.py`)
- CAS legs detected via `segment="nse_cm"` BEFORE the missing-field validation
- CAS symbol: `"NIFTY"` (no strike suffix, no expiry, no opt_type)
- CAS exchange: `"NSE"` (cash), not `"NFO"` (options)
- CAS per-trade cap: tight **0.5%** of cash (vs 5% for options) — caps exposure on Rs.17k-22k per trade
- SELL-leg bypass for credit (unchanged) — only the BUY-side cap tightens

**3. ADX computation** (`scripts/candle_engine.py`)
- Found that `candles_aggregate.json` had NO `adx` field → CAS would never fire
- Added `_adx()` static method (Wilder's smoothing, different from EMA)
- Wired into `compute_indicators()` so it lands in the aggregate file
- Validation: strict uptrend ADX=100, sideways ADX=10, downtrend ADX=100

**4. Tests** (`tests/test_cas_strategies.py`, `tests/test_adx_indicator.py`)
- 20 CAS tests across 5 categories: registration, plan generation, selector triggers,
  routing, exchange field
- 6 ADX tests: pure _adx() + compute_indicators integration
- Test caught a real bug (TypeError on `adx_value > 25` when `candles_aggregate.json` missing)

### Bugs caught + fixed during this work

1. **TypeError on `adx_value > 25`**: original `adx_value = closes` (list) crashed the
   comparison when `candles_aggregate.json` was missing. Fixed to `adx_value = 0`.
2. **CAS exchange hardcoded to NFO**: paper positions would store `exchange="NFO"`
   for cash trades — wrong for MTM/reconcile. Fixed to `"NSE" if _is_cash_leg else "NFO"`.
3. **No ADX in aggregate**: `_adx()` was never written. Wired in.
4. **RSI=0 falsy `or 50` idiom**: downtrend tests had to use realistic up/down variation
   (strict linear decline = RSI=0 = `0 or 50` falls back to 50).

## Current state

- **Time**: Tue Sep 29 2026 13:55 IST
- **Brain**: PID 16112, running on :8503, loaded all new code (CAS strategies + ADX)
- **Markets**: Range-bound today. ADX=5.2 (no trend). CAS won't fire today.
- **Open positions**: 4 NIFTY strangle legs (CE+PE) from iron_condor — already on the books
- **Cash**: Rs.74,185, realized: +Rs.3,972
- **Streak**: 0/10 (rebuilding — day 1 of green streak)
- **Cumulative return**: +5.66% / +15% target

## Verification

End-to-end simulation: synthetic trending day (ADX=30, session_pct=+0.9%, RSI=72)
→ strategy_library picked `nifty_cash_long` with:
- Plan structure: cash_long
- Leg: BUY NIFTY × 75 @ MARKET, segment=nse_cm
- target_pnl: +Rs.17,022
- stop_pnl: -Rs.12,766

CAS is fully wired. On tomorrow's trending day (if any), it should fire.

## Full test results

```
tests/ (excl. test_phase15_fixes.py): 723 passed in 122.34s
tests/test_phase15_fixes.py: 5 pre-existing strike-sanity failures (unrelated to CAS)
```

## Recovery

- **Brain dead mid-session**: `nssm restart KotakKotakBotPaper` won't help — the brain is a
  separate Python process. Write `data_cache/quant_service_restart.json` and the brain's
  in-process scheduler will pick it up and restart cleanly.
- **CAS strategy unwanted**: edit `scripts/strategy_library.py` — comment out the two
  STRATEGIES entries, OR set ADX threshold higher (e.g., adx_above_35).
- **CAS tests failing**: run `pytest tests/test_cas_strategies.py tests/test_adx_indicator.py -v`
  for details.

## Files modified this session

| File | Change |
|---|---|
| `scripts/strategy_library.py` | +2 strategies (cash_long/cash_short), +ADX fallback fix, +ADX-conditional candidate logic |
| `kotak_bot/__main__.py` | +CAS routing (segment, symbol, exchange, cap) |
| `scripts/candle_engine.py` | +_adx() method, +'adx' key in compute_indicators |
| `tests/test_cas_strategies.py` | NEW — 20 CAS tests |
| `tests/test_adx_indicator.py` | NEW — 6 ADX tests |

## Open architecture question (not for this session)

Should CAS strategies have a `_skip_cas.json` flag (like `_skip_day.json`) for when the user
wants to disable CAS on a specific day? Currently the only way to disable is to edit the
strategy library code. A flag pattern would be cleaner.

For now: CAS is wired but conservative — won't fire on range-bound days (ADX<25).