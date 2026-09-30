# Phase 7 Handoff — 2026-10-01 (Data-driven brain)

## What this session delivered

The brain is **no longer a template**. Three new modules replace boolean
threshold checks with probabilistic, learning, regime-aware decisions.
The LLM is no longer the sole risk manager — empirical EV is the safety
net.

### 1. Bayesian EV decision engine (`system/brain/bayesian_decision.py`)

Computes E[LONG], E[SHORT], E[HOLD] from:
- **yfinance prior**: 134+ NIFTY daily samples, computed via `signal_history.empirical_signal_stats()`
- **Local likelihood**: from `trade_journal.jsonl` (filtered for phantoms, RESET, FILL events)
- **Bayesian merge**: smoothing weight = 50 virtual samples for prior (prevents local phantom Rs.1 fills from poisoning prior early on)
- **Unit conversion**: local P&L is in rupees, prior is in percent — divides by `ASSUMED_NOTIONAL` (Rs.100,000) before merging

The brain picks the action with **max positive EV**. Currently both
EVs are slightly negative (-0.12% / -0.02%) → recommends HOLD.

### 2. Online learner (`system/brain/online_learner.py`)

Learns from each trade:
- Recomputes per-strategy, per-side, per-regime win rates from `trade_journal.jsonl`
- Filters: RECON entries with realized_pnl only; skips phantoms, RESET, FILL events
- Persists to `data_cache/learning_state.json` (atomic writes via tmp+rename)
- Provides `get_local_likelihood_for_bayesian()` → feeds Bayesian engine
- Provides `get_lessons_for_prompt()` → injects learned performance into LLM context

After each trade, the local likelihood gains weight. After ~50 real
samples per side, the local likelihood dominates the yfinance prior.

### 3. Regime detector (`system/brain/regime_detector.py`)

Detects regime SHIFTS, not just regime:
- Maintains 60d rolling history of `regime/session_pct/VIX/ADX/nifty_spot` in `data_cache/regime_history.jsonl`
- Flags shift when ANY of:
  - `|session_pct|` > 95th pctile of 60d history
  - VIX > 1.5x median (or < 0.7x)
  - ADX z-score > 2σ vs 60d
  - Current regime < 10% of historical regimes (rare regime)
- `get_regime_shift_context()` → tells LLM "REDUCE conviction, priors may be stale"

When the regime shifts, the LLM is told to be cautious. This is the
"not a template" piece — historical priors are stale in new regimes.

### 4. Brain daemon wiring (`system/brain/brain_daemon.py`)

- **Bayesian EV context** injected into LLM prompt (visible to LLM as `[BAYANIAN DECISION]`)
- **Regime shift context** injected when shift detected
- **Post-LLM Bayesian guard**: if LLM says OPEN but EV strongly negative (n>=30, EV<-0.05%, win<45%) → **SUPPRESS to HOLD**
- **Down-size on weak EV**: if EV mildly negative (n>=30, EV<0, win<50%) → qty halved, trade preserved
- Same guard in `_rule_based_decision` via `_bayesian_suppress()` for LLM-down fallback

The LLM still has final say (it's the primary decision engine), but the
Bayesian guard prevents the LLM from repeating known-losing patterns.

### 5. Proof harness — 60/60 tests pass

```
[PHASE 7 — BAYESIAN + ONLINE LEARNING + REGIME DETECTION]
  ✓ All phase 7 modules import cleanly
  ✓ Bayesian decide() returns full schema
  ✓ Bayesian recommended is hold|long|short
  ✓ Transaction cost in sane range (5-50 bps)
  ✓ Bayesian update: merged win_rate ≈ 0.5125
  ✓ Bayesian update: total n = 160
  ✓ Online learner updates state
  ✓ BUY likelihood returns dict
  ✓ BUY likelihood has valid n>=0
  ✓ Per-strategy breakdown exists
  ✓ All strategy win_rates in [0,1]
  ✓ Regime detector returns dict with required keys
  ✓ Cold start: shifted=False
  ✓ Regime history grows after call
  ✓ brain_daemon has _bayesian_suppress method
  ✓ brain_daemon.cycle has Bayesian guard import
  ✓ Bayesian EV context injected in _call_llm
```

Plus the original 43 tests still pass.

## Files added/modified

### New
- `system/brain/bayesian_decision.py` — Bayesian EV engine (336 lines)
- `system/brain/online_learner.py` — Online learner from journal (411 lines)
- `system/brain/regime_detector.py` — Regime shift detector (298 lines)
- `docs/PHASE7_HANDOFF.md` — this file

### Modified
- `system/brain/brain_daemon.py` — Bayesian guard + prompt injection (144 lines added)
- `scripts/proof_harness.py` — 10 new phase 7 tests (165 lines added)

## Current state

| Service | Status | PID | Uptime |
|---|---|---|---|
| KotakCoreAPI | SERVICE_RUNNING | 20964 | 23m |
| KotakBrainBridge | SERVICE_RUNNING | 5528 | 4h+ |
| KotakBrainDaemon | SERVICE_RUNNING | 5128 | 4m (just restarted with phase 7 code) |
| KotakExecGateway | SERVICE_RUNNING | 13636 | 5h+ |

- **Brain daemon**: restarted 01:53 IST with phase 7 code (PID 5128)
- **Proof harness**: 60/60 tests pass
- **Heartbeats**: all status=ok

## Empirical data findings

- NIFTY daily (246d) yfinance prior:
  - LONG signal (ADX>0.25, RSI>60, trend_5d>0.10): n=24, win=45.8%, Sharpe=-1.51 (loses)
  - SHORT signal (ADX>0.25, RSI<40, trend_5d<-0.10): n=43, win=39.5%, Sharpe=+2.12 (wins)
- Local journal (after phantom filter):
  - BUY: n=14, win=42.86%
  - SELL: n=6, win=50.0%
- Bayesian merge: n=88 LONG, n=99 SHORT, win≈40-45%
- Realized vol (20d): 10.15% → size scale 1.18x
- Adaptive regime: trending_up > +0.33% (80th pctile of 60d history)

## What to do tomorrow (Fri Oct 2, 9:00 IST)

The first real validation day for the data-driven + Bayesian brain.

Expected behavior:
- **Brain recommends HOLD** by default (EVs are slightly negative)
- **LLM may disagree** (it has its own reasoning) → Bayesian guard down-sizes or suppresses
- **Each trade outcome** updates `learning_state.json` → next Bayesian call has better data
- **15:15 IST**: EOD force-square closes positions
- **15:30 IST**: `daily_summary.py` sends Telegram with P&L + readiness

After 5-10 real sessions:
- Local likelihood will have 30+ samples per side
- Bayesian EV will reflect real outcomes, not just historical
- LLM learns from `get_lessons_for_prompt()` which strategies win/lose

## Verification commands

```bash
# Smoke test the 3 new modules
.venv\Scripts\python.exe scripts\_scratch\phase7_smoke.py

# Run proof harness (60 tests)
.venv\Scripts\python.exe scripts\proof_harness.py

# Inspect Bayesian EV
.venv\Scripts\python.exe -c "from system.brain.bayesian_decision import decide; import json; print(json.dumps(decide(), indent=2))"

# Inspect learning state
Get-Content data_cache\learning_state.json | ConvertFrom-Json | Select-Object -ExpandProperty global

# Check regime shift history
Get-Content data_cache\regime_history.jsonl | Select-Object -Last 10

# Force-action restart brain daemon (writes to mavis_force_action.json)
# Bot reads it, kills brain_daemon PID, NSSM auto-restarts
```

## Apply when

- **Adding new data source** (e.g. FII/DII flows, IV surface): add to `signal_history.empirical_signal_stats()` so Bayesian EV incorporates it
- **Brain keeps HOLDing**: check `learning_state.json` global win_rate — if low, real trades need to happen first
- **Brain takes a trade that loses**: check `regime_history.jsonl` for shift detection — if it fired, the LLM was warned
- **EV consistently negative**: `signal_history.empirical_signal_stats()` may need different thresholds — edit and re-evaluate
- **Want to force-trade despite negative EV**: edit `_bayesian_suppress()` thresholds (n>=30 minimum sample guard, EV<-0.05 suppression gate)

## Known issues

- **Local journal still has Rs.1 phantom fills**: filter is in `online_learner._parse_journal_entries()` (skips `phantom_price=true`). Working as designed.
- **Bayesian EV uses ASSUMED_NOTIONAL=Rs.100,000 for unit conversion**: this is paper_capital. If position size changes, update.
- **Regime detector cold-start**: first 10 history entries return `shifted=False`. After ~10 cycles, detector works.
- **LLM still sometimes serial-holder**: the system enforcement fallback (cron-driven) is the last resort. Phase 7 doesn't change that.