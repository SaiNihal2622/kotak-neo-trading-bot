# ADR-002: Pre-flight risk gates at the order-entry boundary

**Status**: Accepted (2026-09-29)

## Context

The current bot's "risk" is enforced AFTER orders are placed. Examples:

- `_max_per_trade_pct` is checked *after* `place_order` succeeded
- `_max_position_pct` is checked the same way
- The SELL-leg auto-snap runs after the order is in the book, hoping
  bid data exists
- LLM can propose `limit=113` for a Rs.12 option; the order sits for 60s
  then times out

This produces orders that **should never have been placed**.

## Decision

Move risk enforcement to a **pre-flight gate** that runs BEFORE `place_order()`
is called. The gate answers three questions:

1. **Does this order fit our current state?** (position cap, cash available)
2. **Is the price reasonable?** (within X% of mid for MARKET, within Y% of
   bid/ask for LIMIT)
3. **Does this fit the strategy?** (multi-leg atomicity check)

If the gate fails, the order NEVER reaches the broker. The LLM gets
rejection feedback within 100ms so it can propose a better plan.

## Consequences

**Good**:
- Impossible to enter broken-condor state (atomicity check)
- Impossible to propose limit=113 when bid=12 (price reasonableness check)
- Impossible to over-allocate (position cap check)
- LLM gets actionable feedback, not silent 60s timeouts

**Bad**:
- Pre-flight needs bid/ask data — if missing, gates must FAIL CLOSED (reject)
- More upfront validation per order (sub-millisecond cost)

## Implementation note

The pre-flight gate is a separate module called by the execution gateway:

```python
def pre_flight_check(order: Order, state: SystemState) -> Result:
    # Position cap: state.used + order.value <= state.position_cap
    # Cash available: order.cash_outlay <= state.cash
    # Limit reasonableness: order.limit <= state.bid * 1.2 (for SELL)
    # Atomicity: if multi-leg plan, ALL legs must fit; if not, reject entire plan
    # Margin: order.margin <= state.available_margin
    return Result(ok=True) or Result(ok=False, reason="...")
```

Pre-flight is the ONLY way to place an order. Bypassing it is a bug.