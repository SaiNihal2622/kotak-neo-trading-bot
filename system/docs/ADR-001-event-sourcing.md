# ADR-001: Event-sourced state with single writer

**Status**: Accepted (2026-09-29)

## Context

The current bot has multiple processes (bot, brain, watchdog, confluence_loop, http_server)
all writing to JSON files on disk. Coordination is via file polling. This has caused:

- 30+ "orphan" / "phantom" / "reconcile" bugs over 6 months
- `close_None` chaos from order_id propagation failures
- Bot state and broker state diverging silently
- File locks + retry logic that masks real failures

## Decision

Replace file-based state with **event-sourced state in SQLite**, with a single
service owning all writes. Every state change is an event row in a write-ahead
log; the current state is the fold of all events.

```
Events are append-only, immutable. State = fold(events).
Single writer per event type. Readers see consistent snapshots.
```

## Consequences

**Good**:
- ACID transactions: `place_order` + `update_position` + `record_fill` in one tx
- Audit trail for free — every state change is queryable
- No file locks, no race conditions
- Subscribers (UI, brain, audit) read snapshots without coordination
- Replay/undo becomes possible

**Bad**:
- More upfront work than "just write JSON"
- All existing bot code paths need updating
- Requires schema design

## Implementation note

SQLite WAL mode gives us:
- Atomic writes (one writer, no fsync contention)
- Read concurrency (readers don't block writer)
- ACID transactions
- Single file (no setup)

This is sufficient for paper trading scale. PostgreSQL only becomes necessary
when multiple processes need to write simultaneously.

For real (live) trading scale: migrate to PostgreSQL with the same schema.