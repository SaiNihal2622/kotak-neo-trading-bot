# ADR-003: LLM out of the hot loop

**Status**: Accepted (2026-09-29)

## Context

The brain (`scripts/quant_service.py`) calls the LLM every few seconds. The
LLM has:
- No memory across calls (same prompt each time)
- No persistent state (re-derives from snapshot)
- No hard constraints (prompt is a soft suggestion)
- No risk awareness across positions (sees 4 legs, not "iron condor")

Observed behavior: 50 BUY orders over 4 hours, all averaging into a long
strangle that the LLM keeps trying to "complete" with SELLs that never fill.

## Decision

Move LLM out of the hot loop. New flow:

```
TIMER (every 15 min, or on regime change):
  1. Read state snapshot from core
  2. Build decision context (one-shot)
  3. Call LLM ONCE: "given this state, what plan do you want?"
  4. Validate plan (pre-flight)
  5. Submit plan to core as a multi-leg atomic operation
  CORE:
  6. Execute legs atomically (all or none)
  7. Update state
  8. Publish "plan_executed" event
  TIMER (next):
  9. Read state, check plan health (PnL, time held, regime drift)
  10. If anomaly: re-consult LLM
  11. Otherwise: hold
```

## Consequences

**Good**:
- LLM has 14+ minutes to think about each plan (vs 5 seconds)
- Plans are atomic — no broken-condor state
- LLM only consulted on actual anomalies (not every tick)
- Cost: 5x lower LLM spend (4 calls/hour vs 60)

**Bad**:
- Slower reaction time to fast market moves (15 min vs 5 sec)
- Need a separate "anomaly detector" to decide when to re-consult

## Implementation note

The "anomaly detector" is rule-based + threshold-based, NOT LLM-based:

- P&L > 50% of target or < 30% of stop
- Time in trade > 70% of max_hold
- Regime change detected by technical signals
- Explicit force-close signal from outside

LLM is for "what to do", anomaly detector is for "when to ask".