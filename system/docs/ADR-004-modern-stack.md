# ADR-004: Technology stack

**Status**: Accepted (2026-09-29)

## Decision

```
BACKEND
  Language:   Python 3.12
  Web:        FastAPI (async, type hints, OpenAPI auto-generated)
  Validation: Pydantic v2 (schemas = types = contracts)
  Storage:    SQLite (WAL mode) for paper + small scale
              PostgreSQL 16 when going live (same schema)
  Async:      asyncio + httpx (LLM calls, broker API)
  ORM:        SQLAlchemy 2.0 (async)
  Locking:    None — single writer service, ACID transactions

FRONTEND
  Framework:  React 18 + TypeScript + Vite
  Styling:    TailwindCSS
  Real-time:  WebSockets (native browser API)
  Charts:     Lightweight Charts (TradingView) or recharts
  State:      Zustand (small, simple)
  Build:      Bun or npm

OBSERVABILITY
  Metrics:    Prometheus client (Python prometheus_client)
  Logs:       structlog (JSON, contextual)
  Traces:     OpenTelemetry (optional, on by default in prod)
  Dashboard:  Grafana (Docker Compose)

DEPLOYMENT (LOCAL)
  Container:  Docker Compose (one file, full stack)
  Services:   core, brain, exec, data, ui, prometheus, grafana
  Process:    NSSM for the core service on Windows
  Networking: bridge network between containers

TESTING
  Backend:    pytest + pytest-asyncio + httpx TestClient
  Frontend:   Vitest + React Testing Library
  E2E:        Playwright (UI flows)
  Load:       locust (when we go live)
```

## Why this stack

**Python 3.12 + FastAPI**: Already the codebase language. FastAPI gives
async + types + auto-docs without bloat. Pydantic v2 makes the JSON schema
the contract between services — types don't drift.

**SQLite + WAL**: ACID transactions, single file, no setup. For a single-
user paper trader this is sufficient. When we go live, switch to PostgreSQL
— same SQL.

**React + TypeScript + Vite**: Modern standard. Type safety on the UI
prevents drift between API contract and what the UI displays.

**Prometheus + Grafana**: Industry standard for time-series metrics. The
trading core exposes `/metrics`, Grafana queries it, dashboards show
PnL, position count, fill rate, LLM latency, etc.

**Docker Compose**: One file deploys the full system. Reproducible across
machines. No "works on my machine" issues.

## What we're NOT using (and why)

- ❌ **Kubernetes**: Overkill for single-user paper trading.
- ❌ **Kafka / NATS**: SQLite + in-process queues sufficient at this scale.
- ❌ **Rust**: Python is fast enough for 1Hz trading decisions.
- ❌ **Next.js / React Native**: Web only, no mobile needed.
- ❌ **Terraform**: Single Windows box, no cloud infra to manage.