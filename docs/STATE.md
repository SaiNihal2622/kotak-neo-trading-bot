# Kotak Neo Bot — Current State

**Last refreshed:** 2026-08-27 10:08 IST
**Session:** mvs_e3e8c628062946d5aa8b0c2a42cac491 (this chat, renamed to "Kotak Neo Bot")
**Legacy context:** see `docs/legacy_session_summary.md` (40K chars from the original long-running session, June–Aug 2025)

---

## Live State (right now)

| Metric | Value |
|---|---|
| Bot status | ✅ Running (4 procs, 4h window) |
| Bot uptime | 1556 s (~26 min) — restarted ~09:42 IST |
| Tick count | 51 (this process) |
| Paper cash | **₹1,13,080.30** |
| Realized P&L | **+₹6,661.10** |
| Open positions | 8 |
| Total orders | 344 |
| NIFTY spot | 24,191.15 |
| BANKNIFTY spot | 57,819.45 |
| India VIX | 10.82 |
| Dashboard :8501 | HTTP 200 |
| HTTP server :8502 | HTTP 200 |
| Last brain decision | neutral, 0 actions, 10:05:43 IST (HOLD — waiting for setup) |
| LiveKotak auth | ✅ authed=True, subscribed=10 |
| bot_stderr.log | clean (no errors) |

## What the bot is doing this tick

`[SCAN] cycle=295 | skip: 2 open strategies >= max 2` — the scan loop is at capacity (max 2 iron-condor-style strategies). New setups are being skipped because we're already at the cap. LiveKotak feed is ticking, LiveIndia is refreshing every ~10s, and the brain is in HOLD mode (neutral bias, no actions).

## Legacy context (June–Aug 2025 — the original long-running chat)

The full summary of the original chat is in `docs/legacy_session_summary.md`. Headline goals and constraints from that era:

- **Goal:** production-grade Kotak Neo API-based Indian options + intraday trading bot. Start in paper, then become "second source of income". 2–3 lots NIFTY + BANKNIFTY options only.
- **Strategy:** regime-based selector — trending → directional, range → iron condor/strangle, event → straddle, volatile → no trade.
- **Constraints:** 2–3 lots, low-risk/high-accuracy preferred, paper first, KOTAK_ENV=uat for paper, KOTAK_ENV=prod+KOTAK_LIVE_CONFIRMED=YES for live. NO HARDCODES anywhere.
- **Crons:** 15+ scheduled jobs (heartbeat, trader-desk, thesis engines, self-monitor, http-watchdog, daily-maintenance, weekly-summary, weekend-intel, nightly-backtest, nightly-improvement).
- **Operational stack:** NSSM (Windows service wrapper), Streamlit dashboard (8501), stdlib HTTP server (8502) for /health /metrics /status.
- **Live mode gates:** 4 conditions must be met (env var, env flip, capital, paper P&L positive for N days). None met yet — still paper.

See `docs/legacy_session_summary.md` for the full 40K-char compaction summary that was extracted from the legacy session's last successful checkpoint.

## Key files in the project

| Path | Purpose |
|---|---|
| `AGENTS.md` | Knowledge file for AI agents (Mavis). Has the Known-issues register, self-evolving policy, recovery procedures. |
| `kotak_bot/` | Production code. Paper-trading bot, broker, feed, risk, regime, order_mgr, alerter. |
| `scripts/` | Operational scripts (cron-driven + utilities). Includes `trader_state.py`, `heartbeat.py`, `thesis_engine.py`, `news_cache.py`, `http_server_watchdog.py`, `self_monitor.py`. |
| `config/settings.yaml` | Settings (paper_capital, lot sizes, strategy params). |
| `config/credentials.env` | TOTP secret, MPIN, Telegram bot token. **Gitignored, do not commit.** |
| `data_cache/` | Runtime state. `paper_state.json` is the source of truth for cash/P&L/positions. `liveness.json` is the bot's liveness ping. `brain_actions.json` is the last trader-desk decision. |
| `system/` | NSSM service entry points (`run_bot.ps1`, `run_dashboard.ps1`, `run_http_server.ps1`). |
| `_archive/` | Dead code kept for reference. Verify before deleting anything here. |
| `docs/legacy_session_summary.md` | Full summary from the original long-running chat (40K chars). |
| `docs/STATE.md` | This file. |

## Current "tombstone" sessions

| Session ID | Title | Project | Status |
|---|---|---|---|
| `mvs_e3e8c628…` | Kotak Neo Bot | kotak-neo-bot | ✅ Active (this chat) |
| `mvs_5487fafc4a0d44038b6c9d4042c98a7d` | Kotak Neo Bot (legacy · from projects root) | projects (parent) | 🔴 Error (context too large, kept as tombstone) |

The legacy session is preserved in three places (snapshot + replacement + backup) totaling 121.5 MB. The session is permanently unopenable due to the 40.5 MB of accumulated context. Backup location: `C:\Users\saini\.minimax\context-backup-20260827-0955\`.

## Recent decisions (last 24h)

- **2026-08-27 09:42 IST:** Bot restarted (PID 5092). Cash landed at ₹1,13,080 (start of session was ₹1,00,000 — the +₹13,080 is mostly today's intraday moves from 2 open iron condors).
- **2026-08-27 09:46 IST:** Legacy chat `mvs_5487fafc4a0d44038b6c9d4042c98a7d` was un-archived, clicked into, triggered `context_compaction_failed`. Re-archived. Backup of full context (40.5 MB) made to `C:\Users\saini\.minimax\context-backup-20260827-0955\`.
- **2026-08-27 10:05 IST:** This current session renamed to "Kotak Neo Bot" so it shows up clearly under the `kotak-neo-bot` project in the sidebar.
- **2026-08-27 10:08 IST:** This STATE.md file written. Legacy summary extracted to `docs/legacy_session_summary.md`.
