# Session Handoff — 2026-09-30 (Phase 6 final)

## What this session delivered

The system is now **non-glued, 24/7, self-improving**, and **production-grade for paper → live transition**.

### 4 NSSM-managed subsystems (auto-restart on crash, survive reboots)

```
KotakCoreAPI      SERVICE_RUNNING  -u -m system.core.api.server     --port 8510
KotakBrainBridge  SERVICE_RUNNING  -u -m system.bridge.brain_bridge --interval 5
KotakBrainDaemon  SERVICE_RUNNING  -u -m system.brain.brain_daemon --interval 120
KotakExecGateway  SERVICE_RUNNING  -u -m system.exec.exec_gateway  --live
```

Plus the legacy `KotakBotPaper` and `KotakDashboard`.

### Real, monitored trading

- Brain daemon makes LLM-driven decisions every 120s, counterfactual recording on each cycle
- Exec gateway fills orders at LIVE NIFTY price from core tick (DIRECT-FILL NIFTY @ 22700.0)
- Bridge posts plans to /api/plan (atomic writes; no [Errno 22] race anymore)
- 638 ghost PROPOSED orders filtered out via KOTAK_STALE_ORDER_SEC=3600

### 4 layers of reliability

| Layer | Frequency | Action |
|---|---|---|
| NSSM | on crash | Auto-restart (5s delay) |
| Heartbeat writers | every 10s | Update data_cache/heartbeat_<svc>.json |
| scripts/watchdog_247.py | every 30s | Restart stale heartbeats via NSSM |
| kotak-bot-watchdog cron | every 5 min | Process-level + log freshness + restart |
| kotak-self-monitor cron | every 15 min | System audit + Telegram anomaly |

## Phase 6 improvements added this session (most recent first)

### Fix 7: Daily reset hook
- At market open, brain daemon clears trading_halted.json so a new day starts clean
- Multi-day runs no longer need manual intervention

### Fix 6: Daily P&L circuit breaker
- Brain daemon checks realized_pnl after each decision
- If below -3% of starting capital (Rs.3000), halt for the rest of the day
- Writes data_cache/trading_halted.json with halt_until timestamp
- Cleared next morning by daily reset hook

### Fix 5: EOD force-square
- 15:15-15:25 IST = force-square window
- Brain daemon writes CLOSE_ALL action to quant_actions.json
- Bridge POSTs to /api/close_all (closes all positions)
- Prevents overnight gap risk; ensures daily P&L is realized before 15:30

### Fix 4: Improved counterfactual
- Now flags BAD OPENs (closed at a loss) not just missed HOLDs
- Daily summary shows win rate, bad_opens count, bad_opens_pnl, good_opens
- Lessons include 'Win rate today: 67% (4W/2L)' for actionable feedback

### Fix 3: Tightened entry conditions
- Multi-signal confirmation now required:
  - Regime + ADX > 0.15 (raised from 0.10) + RSI + VWAP alignment
  - LONG: regime=trending_up + ADX>0.15 + RSI>55 + dist_vwap>0.05%
  - SHORT: regime=trending_down + ADX>0.15 + RSI<45 + dist_vwap<-0.05%
- Reduces over-trading (was 56 OPENs/2hrs in paper mode)

### Fix 2: Clean state.db
- New scripts/reset_state.py (with --dry-run)
- Backs up state.db, deletes order.filled/placed/proposed events
- Resets cash/realized_pnl to baseline
- Used to clear phantom positions from earlier sessions

### Fix 1: Daily summary via Telegram
- New scripts/daily_summary.py
- Aggregates paper_state + counterfactual + live_go
- Sends Telegram at 15:30 with P&L + missed + readiness

### Earlier Phase 6 fixes (already deployed)
- StateProjection filters stale PROPOSED orders (KOTAK_STALE_ORDER_SEC=3600)
- Exec gateway direct-fill from core tick (skips legacy Rs.1 fallback for cash underlyings)
- Bridge/brain daemon atomic JSON writes via system/common/atomic_io.py
- Per-service heartbeats via system/common/heartbeat.py
- Counterfactual module + lessons-injected LLM prompt

## Live state (verified 2026-09-30 20:47 IST)

```
4 NSSM services: all SERVICE_RUNNING, up 0.2min (fresh restart)
heartbeats: all status=ok
positions: 0 (clean after state reset)
open_orders: 0 (ghost filter applied)
realized_pnl: 0 (clean baseline)
cash: 100,000 (clean baseline)
counterfactual cycles today: 59 (13:00-14:59 only — post-NSSM-install cycles are HOLD)
```

## Files modified/added this session

### Added
- system/common/atomic_io.py — atomic JSON writes
- system/common/heartbeat.py — heartbeat + watchdog
- system/brain/counterfactual.py — counterfactual + lessons
- scripts/watchdog_247.py — service health check
- scripts/daily_missed_profit.py — daily missed-profit summary
- scripts/daily_summary.py — daily Telegram summary (NEW this phase)
- scripts/cleanup_stuck_orders.py — reject ghost PROPOSED orders
- scripts/reset_state.py — clean state.db (NEW this phase)
- scripts/install_247_services.py — original NSSM install (has bug)
- scripts/install_247_simple.py — robust NSSM install (NEW this phase)
- docs/SESSION_HANDOFF.md — this file (NEW this phase)

### Modified
- system/core/domain/state.py — stale-order filter, _stale_orders_filtered count
- system/core/api/server.py — heartbeat writer
- system/exec/exec_gateway.py — direct-fill from core tick, heartbeat
- system/bridge/brain_bridge.py — atomic IO, CLOSE_ALL handler, heartbeat
- system/brain/brain_daemon.py — counterfactual, lessons-injection, EOD close, multi-signal entry, daily reset, circuit breaker, heartbeat
- tests/test_brain_daemon.py — updated for new thresholds

## Crons enabled

- kotak-bot-watchdog (every 5 min Mon-Sat) — was paused, now enabled
- kotak-self-monitor (every 15 min) — was paused, now enabled

## Commits this session

```
f7475ff feat(phase6): install_247_simple.py — robust one-shot NSSM install
4866724 docs(phase6): AGENTS.md -- non-glued 24/7 + learning system
a95accc feat(phase6): non-glued 24/7 system -- heartbeats + counterfactual + auto-go-live
```

Plus pending commits for this round of improvements.

## What to do tomorrow (when market opens 9:00 IST)

1. Brain daemon resumes — checks daily_reset hook, clears circuit-breaker
2. First cycle applies multi-signal confirmation (tighter entries)
3. Counterfactual records new decisions + lessons-injection improves next cycles
4. 15:15 IST: auto-closes all positions (no overnight carry)
5. 15:30 IST: daily_summary.py sends Telegram with P&L + missed + readiness

## Verification commands

```bash
# NSSM services
& "C:\Tools\nssm\nssm-2.24\win64\nssm.exe" status KotakCoreAPI
& "C:\Tools\nssm\nssm-2.24\win64\nssm.exe" status KotakBrainBridge
& "C:\Tools\nssm\nssm-2.24\win64\nssm.exe" status KotakBrainDaemon
& "C:\Tools\nssm\nssm-2.24\win64\nssm.exe" status KotakExecGateway

# API
curl http://127.0.0.1:8510/api/state

# Heartbeats (should all be status=ok, age < 30s)
Get-ChildItem data_cache\heartbeat_*.json | ForEach-Object { Get-Content $_ | ConvertFrom-Json | Select service, status, @{n='age_s';e={[int]((Get-Date) - [datetime]::Parse($_.ts)).TotalSeconds}} }

# Daily summary
.venv\Scripts\python.exe scripts\daily_summary.py --send-tg

# Live-go readiness
.venv\Scripts\python.exe scripts\live_go_tracker.py

# Watchdog
.venv\Scripts\python.exe scripts\watchdog_247.py
```

## Apply when

- Adding a new subsystem: register NSSM service, add heartbeat in run_forever(), add to watchdog_247 SERVICE_CONFIGS
- Brain keeps HOLDing: check counterfactual_log for what signals it sees vs what would have OPENed
- Real fills not happening: check heartbeat_exec_gateway.fills counter (0 = WS not subscribed or core API down)
- Service stuck: watchdog_247.py catches within 90s, restart via NSSM
- Phantom positions: run scripts/reset_state.py --dry-run to see, then without to reset
- Daily review: scripts/daily_summary.py --send-tg at 15:30 IST