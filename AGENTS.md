# AGENTS.md

Knowledge file for AI agents (Mavis) operating this codebase. Captures
the **non-obvious** things you have to know to be effective here — not
the obvious stuff that's already in the code or git history.

## Project at a glance

- **What**: Paper-trading bot for Indian NIFTY/BANKNIFTY weekly options.
  Currently in paper mode; live mode requires `KOTAK_LIVE_CONFIRMED=YES`
  + `KOTAK_ENV=prod` env vars.
- **Stack**: Python 3.12, loguru, PyYAML, yfinance, NSSM-managed on Windows.
- **Project root**: `C:\Users\saini\.minimax-agent\projects\kotak-neo-bot`
  (note: `.minimax-agent`, NOT `.minimax` — easy to get wrong)
- **Venv**: `.\.venv\Scripts\python.exe` (Windows path)
- **Logs**: `Logs\bot_stderr.log` (active, written by NSSM redirect).
  `Logs\bot.log` is loguru's own output, also active. Both are gitignored.

## How it actually runs

```
NSSM service "KotakBotPaper" (Automatic, Running)
  → system\run_bot.ps1
    → .\.venv\Scripts\python.exe -m kotak_bot paper
      → kotak_bot\__main__.py :: run_paper()
        → wires broker, feed, risk, regime, order_mgr, alerter
        → installs liveness monitor (data_cache\liveness.json)
        → installs atexit forensic dump (data_cache\liveness_crash.jsonl)
        → main loop: scan, signal, place, monitor
```

```
NSSM service "KotakDashboard" (Automatic, Running)
  → system\run_dashboard.ps1
    → streamlit run dashboard\app.py --server.port=8501 --server.headless=true
```

**Trader-desk cron** (`kotak-trader-desk`, every 5 min 09:00-15:00 Mon-Fri)
runs as a separate Mavis session, NOT inside the bot:
- `python scripts\trader_state.py` reads paper_state + liveness + candles + macro
- Mavis (the LLM) reads that state, makes a decision
- Writes `data_cache\brain_actions.json` (OPEN/CLOSE/HOLD) with rationale
- The bot reads `brain_actions.json` and executes the next tick

The bot does NOT have its own LLM call. The cron IS the brain.

## File organization (current)

- `kotak_bot/` — production code. Imports from here are real.
- `scripts/` — operational scripts. Most are cron-driven; some are
  one-off utilities.
- `config/` — settings.yaml, credentials.env (gitignored).
- `data_cache/` — runtime state. Gitignored.
- `Logs\` — runtime logs. Gitignored.
- `system\` — NSSM service entry points. **These are what NSSM actually runs.**
- `_archive\` — dead code kept for reference. See `_archive/README.md`.
- Root-level `kotak_brain.py` — the LLM brain. **Active.** Imported by
  `scripts/trader_state.py`. Not a "dead alternate orchestrator" despite
  the name.

## The active cron stack (the "24/7" piece)

| Cron name                      | Schedule                | Purpose |
|--------------------------------|-------------------------|---------|
| `kotak-bot-watchdog`           | every 5 min             | NSSM-aware health check + restart if dead |
| `kotak-bot-heartbeat`          | every 5 min             | Wrapper heartbeat (uses temp PS files) |
| `kotak-trader-desk`            | every 5 min 09:00-15:00 Mon-Fri | **The LLM brain** — reads state, decides |
| `kotak-bot-morning-brief`      | 08:15 Mon-Fri           | Telegram pre-market brief |
| `kotak-bot-daily-maintenance`  | 08:25 Mon-Fri           | Power plan, self-test, re-auth |
| `kotak-bot-state-backup`       | 15:45 Mon-Fri           | EOD backup of paper_state.json to Telegram |
| `kotak-bot-weekly-summary`     | Sun 18:00               | Weekly P&L recap |
| `kotak-weekend-intel`          | Sun 21:00               | Weekend intel + Monday brief (NEW 2026-08-22) |
| `kotak-copilot`                | every 10 min 09:00-15:00 | Co-pilot analysis (runs co_pilot.py) |
| `kotak-bot-nightly-backtest`   | 01:00 daily             | Backtest sweep across all strategies |
| `kotak-self-monitor` *(new)*   | every 15 min            | Off-hours self-audit (this file's project) |
| `kotak-nightly-improvement` *(new)* | 23:00 daily         | Self-review + AGENTS.md updates |

## Things to never do

1. **NEVER start a new `python -m kotak_bot` while NSSM is running** —
   you'll have two bots fighting over the same paper state. Use NSSM
   restart instead: `nssm restart KotakBotPaper`.
2. **NEVER edit `Logs\*` directly** — they're NSSM-managed. The bot
   writes via `>>` from the PowerShell wrapper, and a second writer
   causes "process cannot access the file" IOExceptions.
3. **NEVER commit `config/credentials.env`** — it has the TOTP secret,
   MPIN, and Telegram bot token. It's gitignored but force-pushes
   sometimes leak it. If you see it in a diff, abort.
4. **NEVER set `KOTAK_LIVE_CONFIRMED=YES` without explicit user
   authorization** — that's a real-money trade. The user has not given
   that authorization yet.
5. **NEVER change `Logs\` path config in code** — the NSSM service
   writes to `Logs\bot_stderr.log` and `Logs\bot_stdout.log` via
   `AppStdout`/`AppStderr` registry keys. Code that writes to
   `logs\bot_stderr.log` (lowercase) gets a different file and a
   silent divergence.
6. **NEVER delete files in `_archive/` without first re-verifying
   they're dead** — see the verification command in
   `_archive/legacy_orchestrators/README.md`.

## Things to always do

1. **Read `data_cache\paper_state.json` before any decision** — it's
   the source of truth. The bot's in-memory state may be stale.
2. **Read `data_cache\liveness.json` for runtime diagnostics** — has
   `uptime_sec`, `tick`, `main_thread_alive`, and a `snapshot` with
   capital, open positions, VIX, paused flag.
3. **Check `data_cache\liveness_crash.jsonl` for historical crashes** —
   the atexit handler writes here on every clean exit / signal.
4. **Use absolute paths in cron prompts** — the cron's session starts
   in the Mavis data dir, not the project dir.
5. **Use `powershell -NoProfile -ExecutionPolicy Bypass -File <tmp.ps1>`
   for complex PowerShell from bash** — bash strips `$` from inline
   PowerShell, breaking the script.
6. **Commit often, in small logical units** — `git log --oneline` is
   the easiest way to recover from a bad change.

## Recovery procedures

- **Bot dead mid-session**: `nssm restart KotakBotPaper`
- **Dashboard dead**: `nssm restart KotakDashboard`
- **Both services dead**: `nssm start KotakBotPaper`, then
  `nssm start KotakDashboard` (Dashboard should come up first so the
  bot's healthcheck has something to ping)
- **Paper state corrupted**: `python -m kotak_bot reset` (preserves
  capital, clears positions/orders). Document in Telegram.
- **LTM/MCP session lost**: re-auth via the `mcp__kotak_neo__get_login`
  tool + QR scan. Session lasts until the next MPIN re-auth (~24h).
- **Settings changed but bot still has old config**: `nssm restart
  KotakBotPaper` — there is no hot-reload.

## Architecture decisions and why

- **Why NSSM and not systemd/supervisor?** Windows-only box, no WSL.
  NSSM is the standard Windows service wrapper and handles restart-on-
  crash, log rotation, and stdout/stderr redirect cleanly.
- **Why separate trader-desk cron and not put the LLM in the bot?**
  Decouples LLM latency from the 1Hz tick. Trader-desk can take 10-20s
  to decide without blocking the bot. The bot reads the last decision
  on every tick.
- **Why a liveness monitor + atexit handler?** We've seen "clean-exit
  death" patterns where the bot stops without leaving a traceback. The
  liveness file is updated every 30s; the atexit writes a final dump.
  Together they make post-mortem possible.
- **Why paper_capital = 100,000 in config but 300,000 in code?**
  config\settings.yaml has 100,000 as the official "what we trade
  with". The PaperClient constructor in `__main__.py` falls back to
  300,000 if the config is missing. Both are paper; the smaller number
  matches what the user has been tracking in P&L.

## Open architecture questions (to resolve before going live)

1. **Expiry-hold behavior**: currently forced intraday square-off at
   14:30. The user is considering holding credit spreads to Thursday
   14:00 for theta capture. Awaiting decision.
2. **Option chain source**: PROD feed (Kotak Neo scrip master) is
   preferred but has occasional timeout issues. yfinance is a fallback
   for spot LTP only. PRODOI analytics (max pain, PCR, GEX) need a
   proper historical option chain source.
3. **Live mode gates**: 4 conditions must be met (env var, env flip,
   capital, paper P&L positive for N days). Currently all 4 are not
   satisfied.

## Self-evolving / self-learning policy

This file is the institutional memory. Every time you (the agent)
learn something non-obvious about this system — a gotcha, a
recovery procedure, a decision rationale — **add it here**.

Format: one entry per finding, dated, with the rule + the evidence +
when it applies. Don't add one-off trivia. Don't add stuff that's
already in code or git history.

Last reviewed: 2026-08-22 (Mavis operator-mode activation)

## Known-issues register (durable findings)

### 2026-08-22: Orphan bot processes may exist and resist non-admin kill
**Rule**: If `kotak_bot` shows multiple python.exe processes, some of
them may be orphans from previous bot launches. They are typically
in a SYSTEM-owned job object and **cannot be killed without admin**.
**Evidence**: On 2026-08-22 around 18:55 IST, after a manual kill of
the running bot to deploy a liveness fix, NSSM auto-restarted a new
bot (PID 15640) — but TWO additional bot instances (PIDs 12892, 8736,
6908, 10964) from earlier launches survived. `Stop-Process -Force`,
`taskkill /F /T`, all returned `Access is denied`. The orphan 8736
keeps writing the OLD provider code to `data_cache/liveness.json`,
making it look like the liveness fix didn't take effect.
**Apply when**: After any bot restart, verify only ONE pair of
(venv wrapper + system python) is running for the bot. If multiple
pairs, the extras need admin kill (`taskkill /F /T /PID <pid>` from
an elevated shell). The watchdog's `4h window` filter and the
self-monitor's checks still see the new bot as healthy — the
orphan is a *cosmetic* issue for monitoring, not a *functional*
one. **Safe to defer** if the bot is ticking and the dashboard
is up.

### 2026-08-22: Liveness provider mutates a module-level dict
**Rule**: The `_liveness_state` dict in `kotak_bot/__main__.py` is
initialized once with `boot_time` and `phase`, then mutated in place
by the provider on every ping. A previous provider error (e.g.
`RiskState.realized_pnl` AttributeError) is **never cleared** by
successful subsequent calls, so the `provider_error` field stays
stuck in the JSON until the process restarts.
**Apply when**: Adding new fields to the liveness provider — either
clear all error fields at the top of the function, or use a fresh
dict per call. Both work; the per-call-fresh approach is cleaner.

### 2026-08-22: PowerShell 5.1 chokes on em-dash in inline strings
**Rule**: `powershell -Command "...em-dash..."` throws a parser
error. Em-dash and other non-ASCII characters are fine in script
files (UTF-8) but break in inline `powershell -Command` strings.
**Apply when**: Writing PowerShell from bash. Use the temp-script
pattern: write to `%TEMP%\foo.ps1` with UTF-8, then
`powershell -NoProfile -ExecutionPolicy Bypass -File foo.ps1`.
**Gotcha within the gotcha**: bash strips `$` from inline PowerShell,
so any `$variable` becomes `variable`. Use single-quoted strings
inside the temp script, or escape with backtick.

### 2026-08-22: How to kill orphan bot processes that survive Stop-Process /F
**Rule**: When `Stop-Process -Force` and `taskkill /F /T` both return
`Access is denied`, the target process is in a SYSTEM-owned job
object. The fix is to elevate to admin and re-run taskkill.
**Pattern** (works, verified at 22:42 IST 2026-08-22):
1. Write a script that runs `taskkill /F /T /PID <pid>` for each target
   plus verification `Get-Process -Id <pid>` afterwards.
2. From a non-elevated shell, launch it via:
   ```powershell
   Start-Process -FilePath 'powershell.exe' `
       -ArgumentList '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $script `
       -Verb RunAs -WindowStyle Hidden -PassThru
   ```
3. UAC prompt appears; user clicks Yes. Elevated script runs.
4. Read the result JSON file the script wrote for verification.
**Apply when**: Multiple bot instances are running and you can't kill
them without admin. The NSSM service itself does NOT need to be killed —
NSSM will auto-restart the bot if the underlying process dies, so
killing the orphan (not NSSM's bot) is safe.
**Tree awareness**: before killing, walk the parent chain
(`Get-CimInstance Win32_Process | Where-Object {$_.ProcessId -eq X}`)
to make sure you're not killing an ancestor of the live NSSM bot.
In our setup, the live NSSM bot is parented by powershell from
`nssm.exe` (PID 16708 for KotakBotPaper, 6400 for KotakDashboard).
Anything parented by `kite-mcp.exe` or a stray `powershell.exe` is
an orphan.

