# Kotak Trading Core — Production Runbook

## What is this

A real-time paper-trading system that:
- Reads market data from Kotak Neo (prodsockets or REST polling)
- Validates proposed trades against pre-flight risk gates
- Executes orders through PaperClient (paper) or Kotak API (live)
- Logs every state change as an event in SQLite (event-sourced)
- Streams state to a React UI via WebSocket
- Exposes Prometheus metrics for Grafana dashboards

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│  CORE (:8510) — FastAPI + SQLite WAL                    │
│  - POST /api/plan → atomic multi-leg, pre-flight checked │
│  - GET  /api/state → current snapshot                    │
│  - WS   /ws          → live event stream                  │
│  - GET  /api/metrics  → Prometheus                        │
└──────────────────────────────────────────────────────────┘
       ▲ ▲           ▲ ▲
       │ │           │ └──── brain reads state, submits plans
       │ │           └──── UI subscribes for live updates
       │ └──── exec gateway places orders via /api/plan
       └──── Prometheus scrapes /api/metrics
```

## Quick start

```bash
# 1. Start the core service
python -m system.core.api.server --db data_cache/state.db --port 8510

# 2. (Optional) Start the brain
python -m system.brain.brain_service --core http://127.0.0.1:8510

# 3. (Optional) Start the UI
cd system/ui && npm run dev

# 4. (Optional) Start the legacy bot bridge
python -m system.core.migration.bot_adapter --json data_cache/paper_state.json
```

## Docker Compose (full stack)

```bash
docker compose -f system/infra/docker-compose.yml up -d
```

Services:
- `core` — FastAPI on :8510
- `ui` — nginx-served React on :5173
- `prometheus` — :9090
- `grafana` — :3000 (admin/kotak)

## Operations

### Health check
```bash
curl http://127.0.0.1:8510/healthz
# → {"ok": true, "ts": "...", "events_in_log": 1234}
```

### State snapshot
```bash
curl http://127.0.0.1:8510/api/state | jq
```

### Submit a plan (atomic)
```bash
curl -X POST http://127.0.0.1:8510/api/plan \
  -H "Content-Type: application/json" \
  -d '{
    "strategy": "iron_condor_nifty",
    "underlying": "NIFTY",
    "legs": [
      {"symbol": "NIFTY01OCT2622950CE", "underlying": "NIFTY",
       "side": "SELL", "qty": 75, "order_type": "MARKET",
       "strike": 22950, "option_type": "CE", "expiry": "2026-10-01"},
      {"symbol": "NIFTY01OCT2623050CE", "underlying": "NIFTY",
       "side": "BUY", "qty": 75, "order_type": "MARKET",
       "strike": 23050, "option_type": "CE", "expiry": "2026-10-01"}
    ],
    "target": 0, "stop": 0, "confidence": 0, "reason": "range-bound test"
}"
```

### Force-close all
```bash
curl -X POST http://127.0.0.1:8510/api/force_action \
  -H "Content-Type: application/json" \
  -d '{"action": "CLOSE_ALL", "reason": "manual override"}'
```

### Pause / resume
```bash
curl -X POST http://127.0.0.1:8510/api/force_action \
  -H "Content-Type: application/json" \
  -d '{"action": "PAUSE", "reason": "manual"}'

curl -X POST http://127.0.0.1:8510/api/force_action \
  -H "Content-Type: application/json" \
  -d '{"action": "RESUME"}'
```

### View audit trail
```bash
curl http://127.0.0.1:8510/api/audit | jq
```

### View recent events
```bash
curl 'http://127.0.0.1:8510/api/events?types=order.rejected,plan.failed' | jq
```

### View metrics
```bash
curl http://127.0.0.1:8510/api/metrics
```

## Disaster recovery

### Backup
```bash
python -m system.core.backup --db data_cache/state.db --dest backups/
```

### Restore
```bash
cp backups/state-20260929T143022Z.db data_cache/state.db
# Restart the core to load from disk
```

### Reset everything (DANGEROUS — paper only)
```bash
curl -X POST http://127.0.0.1:8510/api/force_action \
  -H "Content-Type: application/json" \
  -d '{"action": "RESET", "reason": "test"}'
```

## Common failures

### "events_in_log count is None"
Fixed in commit `35329aa`. Update to latest.

### SELL orders timing out
PaperClient doesn't have bid data → SELL LIMIT snap can't fire.
Fix: ensure `kotak_prod_feed` is pushing ticks to PaperClient.inject_tick.

### Bot produces open positions that aren't in the core
Legacy bot's _save_state bypasses the event log. Run:
```bash
python -m system.core.migration.bot_adapter --interval 1
```
This bridges JSON → events until the bot is fully migrated (Phase 5).

## Pre-flight risk limits (defaults)

| Limit | Default |
|---|---|
| Max per-trade cap | 5% of cash |
| Max position cap | 30% of cash |
| Max lots per leg | 50 |
| BUY limit must be ≥ | 95% of ask |
| SELL limit must be ≤ | 120% of bid |
| Limit orders require | live tick data |

Edit `system/core/risk/preflight.py:PreFlight.__init__` to change.

## Database maintenance

```bash
# Reclaim space (run during off-hours)
sqlite3 data_cache/state.db "VACUUM"

# Verify integrity
sqlite3 data_cache/state.db "PRAGMA integrity_check"
```

## Logs

The core service logs to stdout. In production, point to a log aggregator:
- JSON format (set `LOGURU_JSON=1`)
- Trace IDs via OpenTelemetry
- Send to Loki / Elasticsearch

## Going live (paper → real)

Pre-flight (in order):
1. **All 9 live-trading gates pass** — `python scripts/live_trading_gates.py`
2. **10 consecutive green paper days** — see AGENTS.md "Go-Live Policy"
3. **Cumulative paper return > +15%**
4. **Avg daily P&L >= Rs.1,000**
5. **Total trades >= 30**
6. Set `KOTAK_LIVE_CONFIRMED=YES` env var
7. Restart core with `--broker kotak_live` flag
8. Verify first 3 fills match expected
9. Monitor for 1 week before scaling up

## Contact

- Bot maintainer: see AGENTS.md
- Pager: configure in Grafana alerts
- Slack #kotak-trading (configure when scaling)