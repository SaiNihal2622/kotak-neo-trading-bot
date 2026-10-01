# Kotak Neo Trading System — System README

**Last updated**: 2026-10-01 23:35 IST (phase 12 final)

## What this is

A paper-trading bot for NIFTY 50 weekly options with REAL MCP plugin
integration. The brain runs inside the Mavis agent runtime where all
7 MCP plugins are directly callable. No stubs, no seed data, no fake
intel.

## Two-tier architecture

```
PRIMARY BRAIN (Mavis runtime):
  kotak-mavis-brain-cycle-phase12 cron (d61c77e8-...)
  → fires every 5 min Mon-Fri 9:00-15:55 IST
  → runs `python -m system.brain.mavis_brain` in Mavis session
  → has REAL access to: puppeteer, fetch, memory, sequential-thinking,
                          kite-mcp, composio, kotak-neo

BACKUP BRAIN (NSSM service):
  KotakBrainDaemon NSSM service
  → runs continuously in BRAIN_DAEMON_MODE=watchdog
  → only writes heartbeat + monitors Mavis cron freshness
  → does NOT run cycles (Mavis cron is the brain)
```

## Plugins ACTIVE

| Plugin | Status | Use case |
|---|---|---|
| `puppeteer` | ✅ | Scrape NSE option chain OI (PCR, Max Pain) |
| `fetch` | ✅ | Direct URL → text for any research site |
| `memory` | ✅ | Persistent knowledge graph across sessions |
| `sequential-thinking` | ✅ | 5-step trade thesis per cycle |
| `composio` | ✅ enabled | 1000+ apps via OAuth (Twitter ready, needs first OAuth) |
| `kite-mcp` | ✅ enabled | Zerodha Kite cross-broker (needs env vars) |
| `kotak-neo` | ✅ | Production broker (uses kotak_prod_feed) |
| `git` | ✅ | Project ops |
| `filesystem` | ✅ | Cross-workspace file access |

## Decision flow (per cycle, every 5 min)

1. **State**: read intraday_levels.json + liveness.json
2. **Live NSE OI**: puppeteer scrapes option chain → PCR + Max Pain
3. **Live trader tweets**: composio pulls Twitter (after OAuth)
4. **Cross-broker**: kite_get_quote() + kotak_get_quote() for price validation
5. **Thesis**: sequential-thinking walks 5-step reasoning
6. **Decision**: Bayesian + Kelly + strategy_selector + adaptive_exits
7. **Persist**: memory MCP entity + local knowledge_graph update
8. **Submit**: kotak-neo MCP if action == OPEN

## Cron schedule

**`kotak-mavis-brain-cycle-phase12`** (active):
- Schedule: `*/5 9-15 * * 1-5`
- Fires: every 5 min Mon-Fri 9:00-15:55 IST
- First fire: tomorrow (Fri Oct 2) 9:00 IST
- Session: `mvs_caea2ecdf9984a3f995bd27ab6a8123b` (this session)

## Manual operations

### Resume NSSM brain_daemon (admin required)

The NSSM service is currently `SERVICE_PAUSED`. Resume it manually:

```cmd
:: Right-click → "Run as administrator"
scripts\RESUME_NSSM_AS_ADMIN.bat
```

Or in admin PowerShell:
```powershell
& 'C:\Tools\nssm\nnssm-2.24\win64\nssm.exe' continue-service KotakBrainDaemon
& 'C:\Tools\nssm\nnssm-2.24\win64\nssm.exe' start KotakBrainDaemon
```

### Force-restart brain daemon from any cycle

Write `data_cache/mavis_force_action.json`:
```json
{"action": "RUN_COMMAND", "command": ["taskkill", "/PID", "<pid>", "/F"], ...}
```

### Reseed knowledge graph

```bash
.venv\Scripts\python.exe scripts\_scratch\reseed2.py
```

### Run proof harness (111 tests)

```bash
$env:PYTHONIOENCODING = 'utf-8'
.venv\Scripts\python.exe scripts\proof_harness.py
```

### Test watchdog mode locally

```bash
$env:BRAIN_DAEMON_MODE = 'watchdog'
$env:PYTHONIOENCODING = 'utf-8'
.venv\Scripts\python.exe scripts\_scratch\test_watchdog4.py
```

## Configuration

### Env vars in `config/credentials.env`

```bash
# Already set:
TELEGRAM_BOT_TOKEN=8859774824:AA...
TELEGRAM_CHAT_ID=8537408638
MINIMAX_LLM_API_KEY=sk-cp-...

# Phase 12 placeholders (fill in to enable):
KITE_USER_ID=        # your Zerodha client ID
KITE_PASSWORD=       # your Zerodha password
KITE_API_KEY=        # from https://developers.kite.trade/
KITE_API_SECRET=     # from Kite Connect app
KITE_TOTP_SECRET=    # base32 TOTP secret
```

### NSSM env vars on `KotakBrainDaemon`

```
PYTHONIOENCODING=utf-8
BRAIN_DAEMON_MODE=watchdog
```

(These are already set; just needs the service to be resumed.)

## Phase 12 deliverables

- `system/common/mcp_helpers.py` (266 lines) — unified MCP import surface
- `system/brain/mavis_brain.py` (408 lines) — in-Mavis brain runner
- `system/brain/brain_daemon.py` — added `BRAIN_DAEMON_MODE=watchdog`
- `scripts/RESUME_NSSM_AS_ADMIN.bat` — admin helper to resume service
- `scripts/proof_harness.py` — 111 tests pass (was 60 before phase 7)
- Cron `kotak-mavis-brain-cycle-phase12` registered
- AGENTS.md updated with phase 12 architecture

## Trade-offs vs 100% uptime

| Risk | Mitigation |
|---|---|
| Mavis session dies | Watchdog cron monitors heartbeat, alerts if stale |
| NSSM service paused | Manual resume (admin needed) or auto-respawn if process dies |
| MCP plugin fails | Graceful fallback to local data (knowledge_graph, web_search) |
| Broker downtime | Circuit breaker (-3% daily) + EOD force-square |
| Internet loss | All 4 NSSM services + watchdog + crons are 24/7 |

## What's NOT done (optional)

- **kite-mcp env vars**: need Kite Connect app credentials. After fill-in,
  cross-broker validation works immediately.
- **composio Twitter OAuth**: first `composio_search_twitter` call triggers
  browser flow at `connect.composio.dev/mcp`. 100 free actions/month.

## Tomorrow's expected behavior

At 9:00 IST (Fri Oct 2):
1. Mavis cron fires `python -m system.brain.mavis_brain`
2. Brain cycle runs in Mavis session with REAL MCP plugins
3. Each cycle touches 6+ plugins
4. Decisions logged to `data_cache/quant_actions.json`
5. Knowledge graph persists cross-session via memory MCP
6. Watchdog (NSSM, when resumed) confirms Mavis cycle freshness

This is the FIRST market day with full plugin integration.
Expect 0-3 trades as the system learns the new regime.
