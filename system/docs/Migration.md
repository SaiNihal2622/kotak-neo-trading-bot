# Migration path: legacy bot → new system

## Strategy

Keep the existing bot RUNNING while we migrate. The new system is built
alongside. The bot writes to JSON files (as today). The new core owns a
SQLite DB. They both read from the broker (PaperClient) for fills.

**Migration phases** (each phase ships without breaking the previous):

### Phase 0 — Dual-write (today)
- Existing bot writes JSON files AS USUAL
- New core ALSO writes the same data to SQLite (passive listener)
- Verify consistency: bot's `paper_state.json` matches SQLite's `paper_state` table

### Phase 1 — Bot reads SQLite for status queries
- Bot's status endpoint queries SQLite, not JSON
- JSON files still written (for backward compat)
- One-way: SQLite is now the read source

### Phase 2 — Bot writes to SQLite (primary), JSON is backup
- Bot's `_save_state()` writes to SQLite (transactions, ACID)
- JSON files written ONLY on bot shutdown (for archival)
- Bot reads ONLY from SQLite

### Phase 3 — Bot routes orders through core API
- Bot no longer calls `broker.place_order()` directly
- Instead calls `core.submit_order()` (which runs pre-flight)
- Pre-flight rejects bad orders BEFORE they hit the broker
- Bot reads results via WS subscription

### Phase 4 — Bot becomes a "client" of the core
- Bot is just a service that proposes plans to the core
- All state mutations go through the core
- Bot is replaceable (could be a CLI, a Jupyter notebook, anything)

### Phase 5 — New system takes over
- Old bot is decommissioned
- Core service runs as a daemon (NSSM on Windows, systemd on Linux)
- New brain service consumes events from core and proposes plans

## Today's actual work (Phase 0)

Right now we're just at:
- ✅ Core service built (`system/core/`)
- ✅ Pre-flight risk gates implemented
- ✅ Event-sourced state in SQLite
- ✅ Tests pass for the core (11 tests)
- ⏳ New UI not deployed (needs `npm install` + build)
- ⏳ Bot not migrated yet (still writes JSON)

## Backwards compatibility

Until Phase 5, the bot continues to:
- Run as KotakBotPaper NSSM service
- Write paper_state.json, trades_state.json, etc.
- Use PaperClient for fills

The new core runs in PARALLEL (different port, 8510 vs 8511 for brain).

## How to run the new system today

```bash
# Start core (uses same DB as legacy bot, read-only at first)
.\.venv\Scripts\python.exe -m system.core.api.server --db data_cache/state.db --port 8510

# Test it
curl http://127.0.0.1:8510/healthz
curl http://127.0.0.1:8510/api/state

# Open UI (in dev mode)
cd system/ui
npm install
npm run dev
# Browse to http://localhost:5173
```

## What gets validated at each phase

| Phase | Test | Pass criteria |
|---|---|---|
| 0 | Bot state == SQLite state | Both have same cash/positions/P&L |
| 1 | Bot reads from SQLite | Status endpoint shows same numbers |
| 2 | Bot writes to SQLite | JSON files no longer being updated |
| 3 | Pre-flight blocks bad orders | LLM can't propose limit=113 anymore |
| 4 | Bot is stateless | Core is the only writer |
| 5 | Bot is gone | Core handles everything |