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

0. **NEVER rely on `mavis_force_action.json` or `brain_actions.json` channels without verifying the bot's `__main__._read_json` and brain_actions reader are both present.** The 2026-08-27 BNF close-failure was caused by `_read_json` being referenced in the force-action block but never defined in module scope — the try/except around the call silently swallowed the NameError, so Mavis's 12:10 + 12:21 CLOSE actions never executed. See "Known-issues register" entry below.
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

Last reviewed: 2026-08-30 (Mavis nightly-improvement, false-positive liveness_ping_failed documented)

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

### 2026-08-22: Kotak PROD API throws ~1-4 URLErrors per 24h on quiet weekends; the bot self-recovers
**Rule**: The Kotak Neo PROD endpoint `e22.kotaksecurities.com` returns
two flavours of transient error ~1-4 times per 24h on quiet (weekend)
days: (a) `urllib.error.URLError: <urlopen error timed out>` after 15s,
(b) `urllib.error.URLError: <urlopen error [WinError 10054] An
existing connection was forcibly closed by the remote host>`. Both
originate at `kotak_bot/data/kotak_prod_feed.py::_fetch_spot_quotes:606`
→ `_poll_loop:547` (one loguru ERROR per failed poll). The
`_poll_loop` exception handler catches these and the next 60s poll
cycle succeeds — **no operator action is required**.
**Evidence**: On 2026-08-22, stderr logged exactly 4 of these in 24h
(19:09:20 timeout, 19:52:44 WinError 10054, 19:53:52 timeout,
22:25:56 timeout). All 4 self-recovered; subsequent INFO heartbeats
(22:28:01 onwards) show `tick_count 25326→...` advancing at +56/min.
Telegram was sent ONCE for the 22:25:56 cluster (22:30, message_id
1269); the earlier 19:09/19:52/19:53 cluster did NOT alert, indicating
the alert policy is throttled to ~1 per N-hour cluster.
**Apply when**:
- Reading `Logs\bot_stderr.log` and seeing a `kotak_prod_feed:
  _poll_loop:547` URLError — check whether the next 60s line is a
  fresh `LiveKotak heartbeat: tick_count=...`. If yes, the bot
  recovered and no action is needed. Do NOT restart, do NOT Telegram.
- The error is upstream (E22 load balancer), not a client bug.
  Do NOT bump the 15s timeout or add a retry without a separate
  decision — the current back-off-via-next-poll pattern is correct.
- If you see >5 of these within a single hour (vs the usual 1-3
  per day), the upstream may be having an outage worth investigating.
- WinError 10054 specifically = remote-side TCP RST. Correlates with
  brief outage clusters, not a single bad request.

### 2026-08-27: `_read_json` is undefined in `__main__` — force-action channel silently broken

**Rule**: `kotak_bot/__main__.py` calls `_read_json(...)` at the top of the main loop (force-action channel for `data_cache/mavis_force_action.json`), but the function is **not defined in module scope and not imported**. The reference exists only in `scripts/live_dashboard.py` and other scripts. The try/except around the call site catches the resulting `NameError` and logs it as `logger.debug(...)`, which means it never appears in normal log inspection.

**Evidence (2026-08-27)**: BNF condor (short 57,700 PE) breached the strike at 12:10 IST. Brain issued a CLOSE action with `act-1210BNFCL` to `data_cache/brain_actions.json` (300s TTL). Bot did not execute. At 12:21 brain reissued as `act-1221BNFCLRE` to `brain_actions.json` (loss-cutting reissue, BNF now -98pt ITM). Bot did not execute. Brain noticed the channel was broken at 12:26:01 (`note: "...force_action_channel_broken_bot_cannot_close_undefined_read_json_in_main_848_14_30_force_square_2h04m_backstop_nifty_comfortable_pe_buffer_46pt"`). Investigation confirmed `_read_json` is never imported, never defined in `__main__.py`. **Bot also doesn't read `brain_actions.json` at all** — that channel did not exist in the codebase. The 12:10 + 12:21 brain writes were unread by the bot from the moment they were written.

**Fix shipped 2026-08-27 12:30 IST** (this commit):
1. Added `def _read_json(path, default=None)` at module level in `__main__.py` (right above `init_csv`), with utf-8-sig handling matching the pattern in `scripts/live_dashboard.py`.
2. Promoted the silent `logger.debug("force-action check failed: ...")` to `logger.warning(...)` so this class of bug surfaces in normal log inspection.
3. Added a brand-new `brain_actions.json` reader in the main loop (block 1b). Mavis CLOSE actions with `ttl_sec <= 600` and a `consumed=False` flag are now executed within 5-30 sec. `consumed=True` is written back so we don't repeat. Per-leg closes use `square_off_all()` (the cleanest path; the reason field logs the intended scope).

**Constraint at time of fix**: An orphan `python.exe -m kotak_bot paper` (PID 10184, started 2026-08-27 09:41:37, owned by SYSTEM via NSSM parent) survived the death of the NSSM-tracked PowerShell wrapper at 09:40:41 IST (parent 10148 died, the python child was orphaned to SYSTEM). This orphan is running the OLD code. `Stop-Process -Id 10184 -Force` and `taskkill /F /T /PID 10184` both return "Access is denied" without admin elevation. The 14:30 force-square-off is the bot's backstop. The fix is in the file and will take effect on the next bot restart (or when this orphan is killed via admin UAC).

**Resolution (2026-08-27 evening)**:
- Orphan 10184 died with `reason=signal` at 20:29:32 IST (UTC timestamp `+00:00` in liveness_crash.jsonl = 14:59:32 UTC = 20:29:32 IST). The signal came from an external kill.
- The atexit handler ran startup_reconcile on the orphan's death, which placed 8 close MARKET orders at 20:29:27-28 IST. All filled at EOD reference prices:
  - NIFTY 24300CE: closed @ 17.50 (was 87.01) → +₹4,518 on short
  - NIFTY 24400CE: closed @ 4.23 (was 50.73) → +₹3,023 on long (the long was nearly worthless)
  - NIFTY 24100PE: closed @ 21.85 (was 42.98) → -₹1,373 on short
  - NIFTY 24000PE: closed @ 5.53 (was 23.56) → +₹1,170 on long
  - BNF 57900CE: closed @ 21.26 (was 826.34) → +₹24,152 on short
  - BNF 58000CE: closed @ 47.44 (was 770.44) → +₹21,690 on long
  - BNF 57700PE: closed @ 242.55 (was 580.66) → -₹10,143 on short (BNF PE was deep ITM at 14:30, only 47.55pt left of wing)
  - BNF 57600PE: closed @ 177.07 (was 543.27) → +₹10,986 on long
  - **Net NIFTY condor: +₹1,697. BNF condor: +₹1,620. Day P&L: +₹3,317.**
- Fresh bot PID 14876 started 2026-08-27 23:38:51 IST, picked up the b273669 fix (verified `_read_json`, brain_actions reader, force_action reader all present in source).
- Capital landed at ₹1,09,978 (started ₹1,00,000, +₹9,978 paper).
- Telegram update sent to user at 00:47:30 IST (msg_id 1881, chat 8537408638).

**Apply when**:
- Any new module in `kotak_bot/` calls a function that should be defined elsewhere — verify it's in module scope or imported. Do NOT assume a function name; grep for `def <name>` in the package directory.
- Adding any new "external control" channel (file-based, IPC, signal-based) to the bot — write a small unit test that exercises the path end-to-end, and add a `logger.warning` (NOT debug) for any catch-block that swallows exceptions. Silent debug-level error swallowing is a recurring footgun in this codebase.
- Reviewing future bot failures where Mavis wrote an action and the bot didn't execute it — first check the bot's log for `force-action check failed` or `brain-action check failed` warnings.
- Diagnosing "why did NSSM's app appear running but the process was gone" — check for orphan python children owned by SYSTEM. They're a real risk in the NSSM-managed launch pattern; recommend adding a `kill /F /T /PID <wrapper>` to the recovery flow so the child doesn't get orphaned to SYSTEM.

### 2026-08-28: FOLLOW-UP — duplicate `from pathlib import Path` shadowed `Path` as a local in `run_paper()`, breaking BOTH action channels even after the _read_json fix shipped

**Rule**: The 2026-08-27 12:30 fix added `_read_json` and a new `brain_actions.json` reader in `kotak_bot/__main__.py:run_paper()`, but it left an unprefixed `from pathlib import Path` at line 1037 (compliance-PDF block). Python's compiler sees ANY `from X import Y` inside a function and marks `Y` as a LOCAL for the entire function. Subsequent `Path(...)` calls at lines 863 (force-action) and 912 (brain-action) then raise `UnboundLocalError: cannot access local variable 'Path' where it is not associated with a value` at runtime, which the try/except catches and logs as a WARNING every 5s. **Result: BOTH Mavis action channels were silently broken even after the 12:30 fix — the fix was incomplete.**

**Evidence (2026-08-28)**: `bot_stderr.log` shows the warning firing every 5s from 08:01 IST onwards (after the bot restarted at 08:31), 200+ times in the first 2 hours:
```
WARNING | force-action check failed: cannot access local variable 'Path' where it is not associated with a value
WARNING | brain-action check failed: cannot access local variable 'Path' where it is not associated with a value
```
The startup-integrity check at line 244 also failed the same way (`[STARTUP-INTEGRITY] check skipped: cannot access local variable 'Path'`). Bytecode analysis of the live `__pycache__` confirms: `Path` is in `co_names` (LOAD_GLOBAL), but the inner `from pathlib import Path` at line 1037 makes the compiler mark `Path` as local. The outer `from pathlib import Path as _Path` at line 793 ONLY binds `_Path` as local — the bug is specifically the unprefixed re-import at line 1037.

**Fix shipped 2026-08-28 09:04 (uncommitted in working tree) → committed 30c0fc9**: removed the `from pathlib import Path` at line 1037 and replaced with a comment explaining why not to re-import. After NSSM restart (or natural process recycle), the warnings stopped. Verified: last Path WARNING in bot_stderr.log was ~09:08 IST; from 09:09 onwards the channels are clean.

**Apply when**:
- Adding a NEW `from X import Y` (without alias) inside any function that already references `Y` elsewhere in the same function — the unprefixed import will shadow the module-level `Y` for the ENTIRE function scope, breaking every `Y(...)` call before the import. Use `from X import Y as _Y` if you need a function-local import, OR put the import at the top of the function (before any use), OR (best) rely on the module-level import.
- Reviewing the 2026-08-27 _read_json fix — the original fix added the reader but introduced this new bug. Test pattern: after any code change that adds an import inside `run_paper()`, run a 60s test and `grep "WARNING | .* check failed"` in `Logs\bot_stderr.log`.
- Looking for "silent" code-channel breakage in this bot: any try/except that logs at WARNING level can mask a recurring error. The fact that this fired every 5s for 2+ hours without being caught is a sign the heartbeat / self-monitor pipeline needs a stricter "recurring WARNING rate" alert (a per-minute count of identical WARNINGs would have flagged this in 5 min, not 2 hours).
- NSSM restart from a non-elevated shell: returns "Access is denied" silently (no UAC prompt, just exit 3). The only path is `Start-Process -Verb RunAs` from a non-elevated shell, which surfaces the UAC prompt — and if the user isn't at the console, it gets cancelled. Document this so future self-driver sessions don't waste a tick trying to restart.

### 2026-08-22: kotak-bot-heartbeat cron checks the VESTIGIAL log, not the active one
**Rule**: The `kotak-bot-heartbeat` cron prompt (cronId
`3fc44c8d-b1e2-4606-9812-d7b9cec0f78e`, every 5 min) tells the LLM
to run `Select-String -Path 'bot_stderr.log' -Pattern
'Traceback|FATAL|Killed|Exception' | Select-Object -Last 3`. The
relative path resolves to `C:\Users\saini\.minimax-agent\projects
\kotak-neo-bot\bot_stderr.log` (lowercase, no `Logs\` prefix) — the
**vestigial** file frozen at 2026-08-20 02:27:15. The canonical
active log is `Logs\bot_stderr.log` (capital L, NSSM-managed,
currently ~169 KB and growing). The cron's "new error" detection
therefore reads a dead file and can **never** find a new Traceback
in the active log.
**Evidence**: The heartbeat prompt itself contains a comment
"ROOT, NOT `Logs\bot_stderr.log` which is stale" — but this is
inverted. `Logs\bot_stderr.log` is the canonical NSSM-managed
log (see "Things to never do #5" above), and the ROOT lowercase
file is the stale one. The 22:25:56 URLError was logged to
`Logs\bot_stderr.log` and the 23:00 self-audit found it correctly;
the 23:00 kotak-bot-watchdog session, following the spec verbatim,
found nothing because it read the wrong file.
**Apply when**:
- Investigating "did the bot have a new error?" — read
  `Logs\bot_stderr.log` (capital L), NOT `bot_stderr.log`. The
  self-monitor cron (which uses `data_cache\self_audit.jsonl` and
  `self_monitor.py`) reads the right file and is the more reliable
  signal.
- The fix (rewrite the cron prompt's Select-String path) is a
  small but running-behavior change. Do not change in a hurry.
  When you do, ALSO add a "lines newer than the bot's start
  time" filter so the dead-file pattern doesn't fire
  post-fix on historical 8/14 noise (the prompt already has this
  filter written; just the path needs to point at `Logs\`).

### 2026-08-28: yfinance fetch fails silently on empty DataFrame during off-hours
**Rule**: `yf.Ticker(SYMBOL).history(period="1d")["Close"].iloc[-1]` raises
"single positional indexer is out-of-bounds" when the DataFrame is empty
(weekends, US holidays when NSE is also closed, late-night IST windows).
The old `_fetch_spot` in `scripts/mavis_monitor.py` swallowed this in a
broad `except Exception` and logged it as `[warn] yfinance fetch failed:`
~60 times per 24h, polluting `logs/mavis_monitor.log` and making real
errors hard to spot.
**Fix shipped 2026-08-28 06:05 IST** (this commit): added
`_is_market_hours(now)` (Mon-Fri 08:30-15:45 IST) and `_safe_yf_close(symbol)`
which returns 0.0 silently on empty DataFrame and only logs on real
network/API errors. The main loop now gates `_fetch_spot()` on
`_is_market_hours`; during off-hours the yfinance call is skipped entirely,
so 1440 calls/day drop to ~390. Health checks (bot liveness, dashboards,
log staleness) still run 24/7.
**Apply when**:
- Reading `logs/mavis_monitor.log` and seeing `[warn] yfinance fetch failed` —
  these should now be rare. If you see a cluster, it means a real upstream
  problem, not just off-hours noise.
- Adding new yfinance fetches to other scripts — copy the
  `_safe_yf_close` pattern, or import from mavis_monitor. The empty
  DataFrame case is the most common error.
- Same pattern exists in `scripts/mavis_realtime.py` `_fetch_spot`
  (lines 107-131) but is not yet fixed there. Apply when convenient.
  **(Fixed 2026-08-30 — same `_is_market_hours` + `_safe_yf_close` pattern applied
  in this same fix pass; the empty-DataFrame case is now silent during off-hours.)**

### 2026-08-30: mavis_realtime.py silent death — orphan reaping pattern
**Rule**: `scripts/mavis_realtime.py` writes `data_cache/mavis_realtime_state.json`
and `data_cache/mavis_events.jsonl` (powers the dashboard's "Mavis Live" + Event
Ticker sections). When launched via plain `Start-Process -FilePath python.exe ...`
from a parented PowerShell, the resulting python child becomes orphaned when
the parent exits. The orphan gets reaped silently within 30-60 minutes — no
error, no exit log, just stops writing. Symptom: dashboard sections freeze
on 2-3-day-old data; the respawn cron fires but the new launches are also
orphans and also die.

**Evidence (2026-08-30)**: After my 02:46 IST restart via plain Start-Process,
the script ran 34 min then died at 03:20:38 with no error. Log was clean
(`cycle=681 NIFTY=0.00 BNF=0.00 ...`), no `=== Mavis real-time rotating ===`
exit message — just stopped. State file became 998 min old. Dashboard
`/api/mavis_state` returned frozen 2026-08-27 data.

**Fix shipped (2026-08-30 20:08 IST)**:
1. **`system/run_mavis_realtime.ps1`** — self-respawning wrapper. Loops forever,
   launches `python -u scripts\mavis_realtime.py` via Start-Process, waits
   for exit, waits 5s, relaunches. The wrapper is a long-lived powershell,
   so the python child is NEVER an orphan.
2. **Detached launch via `cmd /c start /B powershell.exe ...`** — the wrapper
   itself is reparented to SYSTEM (parent = empty), so it survives the
   Mavis session that launched it.
3. **Respawn cron updated** to look for the WRAPPER (run_mavis_realtime.ps1),
   not the python directly. If wrapper is dead, relaunch detached.
   Old cron's `python` Start-Process pattern was the bug — the new one uses
   `cmd /c start /B powershell.exe`.
4. **Verified at 20:08**: detached wrapper PID 13956 (parent reparented to
   SYSTEM) → python 16996 → python daemon 17880. State file age = 1 sec.
   `/api/mavis_state` returns `ts: 2026-08-30T20:07:24, is_watching: true`.

**Apply when**:
- Adding new long-lived polling/streaming scripts in `scripts/`: launch them
  via `system\<name>_wrapper.ps1` with the same pattern, NOT plain Start-Process.
  The wrapper is a tiny PowerShell that loops, launches the python, waits for
  exit, relaunches. Two layers of persistence.
- Reviewing the cron `kotak-mavis-monitor-respawn`: it watches the wrapper,
  not the python. If the cron prompt changes back to checking for the python
  directly, the orphan-reaping bug returns.
- Future "proper" fix when admin access is available: install the wrapper as
  an NSSM service (`nssm install KotakMavisRealtime powershell.exe -File
  system\run_mavis_realtime.ps1`). NSSM handles restart-on-crash and survives
  everything. The current wrapper-based approach works without admin, but
  NSSM would be cleaner for production.

### 2026-08-30: Three data sources silently dead, mavis_realtime fix unmasks the rest
**Rule**: The dashboard reads from 8 API endpoints. Each points at a different
data file. When the user said "still no correct dashboard" after the
mavis_realtime fix, the unfixed endpoints were:
- `/api/mavis_state` (FIXED 20:08, see above)
- `/api/quant_brain` — reads `data_cache/quant_brain.json`, written by
  `scripts/quant_brain.py` (one-shot, cron-driven). Last write 2026-08-26
  22:25 IST = 3.9 days stale. Will refresh next cron fire (8:25 daily).
- `/api/mavis_trades` — reads `data_cache/mavis_trades.json`, written by
  `scripts/mavis_premarket.py` (one-shot, 8:35 cron). Last write 2026-08-28
  08:35 IST = 2.5 days stale. Will refresh Monday 8:35 cron.

**Apply when**: If user reports "dashboard not working", check ALL data
source ages with `Get-ChildItem data_cache\*.json | Select Name, LastWriteTime`.
Don't just trust the live process — every JSON file is its own dependency.

### 2026-08-30: Structural fix for Mavis context-too-large killer (the real one)

**Rule**: A single 3.6MB tool result bakes itself into the assistant message's
`tool_call_result_data` field, and the runtime's checkpoint generation cannot
recover from it. The previous sanitizer hook only knew about 4 tool families
(`bash`/`read`/`filesystem`/`puppeteer`) and the `memory` and `mavis` tools
sailed through untruncated. A single `memory` read of MEMORY.md (3.6MB) or a
single `mavis session messages --limit 20` (still 900KB because individual
messages are large) was enough to kill the session at the next checkpoint.

**Evidence (2026-08-30)**:
- `mvs_fddaffedef47489491056112be947e73` (the user's complaint): 6.46MB / 117 msgs, biggest msg 2831KB
- `mvs_47cf562d0ce2451aad1d6be4aa97c51b` (the "fix it" session that died the same way): 5.10MB / 74 msgs, biggest msg **3623KB** from `memory` tool reading MEMORY.md
- Field breakdown across the 4 most-recent dead sessions: 99.4% of big-message bytes were in `tool_calls[].tool_call_result_data`. The actual `msg_content` was 0%.

**Fix shipped (this commit)**:
1. **Sanitizer v2** at `C:\Users\saini\.minimax\agents\mavis\hooks\sanitize_tool_result.py`:
   - Added explicit `memory` tool branch: full content saved to disk, return head (5 lines) + tail (200 lines) summary.
   - Added catch-all branch: any tool result > 50KB that wasn't already sanitized gets capped with overflow to disk.
   - Fixed `mavis session messages` matcher: previously checked `tool_name` only, but the MCP tool name is just `"mavis"`. Now also matches `args.command == "session messages"` (handles both flat and `args.args.limit` nested paths).
   - Verified: 3.6MB memory result → 10.1KB; 980KB mavis result → 5.1KB; 4MB unknown-tool result → 5.1KB. All 5 unit tests pass.
2. **SessionStart hook** at `C:\Users\saini\.minimax\agents\mavis\hooks\session-start-handoff.md`:
   - On every new session, scans for `data_cache/session_handoff.md`. If present, writes per-session state file to `data_cache/_handoff_state/<sessionId>.json` with `injected: false`.
3. **UserPromptSubmit hook** at `C:\Users\saini\.minimax\agents\mavis\hooks\user-prompt-handoff.md`:
   - On the first user prompt of each session, reads the state file and prepends the handoff content (capped at 12KB) as a `SYSTEM CONTEXT` block before the user's actual message.
   - Marks `injected: true` so subsequent prompts pass through untouched. One-shot, idempotent, no rewrite when no handoff.
4. **Session janitor** at `C:\Users\saini\.minimax\agents\mavis\scripts\session_janitor.py` (new cron `kotak-session-janitor`, every 5 min):
   - **STRIP pass**: for active sessions > 1.5MB total, walk back through older assistant messages (skip the most-recent 30) and null out `tool_calls[].tool_call_result_data` from those where the LLM has already produced a conclusion (`msg_content` is non-empty). Replaces with a short `[stripped by session_janitor: original ~X chars from <tool>; call again if needed]` reference. Truncates `tool_call_args` > 200 chars.
   - **HANDOFF pass**: for active sessions > 3MB total, write a fresh `data_cache/session_handoff.md` capturing the last 20 turns.
   - Verified: 60-msg / 1.44MB synthetic test session → 0.73MB (50% reduction), 15 tool results stripped, no recent context lost.
5. **Existing `kotak-session-hygiene` cron prompt** updated to reference the new fix and treat new FAILs as regressions.

**Apply when**:
- Investigating any "Mavis session died of context_compaction_failed" incident — the cause is almost certainly one large tool result, not accumulated small ones. Look at the biggest single message, find its `tool_call_result_data`, and verify the corresponding tool is in the sanitizer's catch-all path.
- Adding a new MCP server or builtin tool that can return large results: copy the catch-all pattern (it's already there as the default). The sanitizer will catch any tool > 50KB regardless of name.
- Reviewing "why does the LLM sometimes have stale context" — the janitor strips tool results from messages older than the most-recent 30. The LLM has the conclusion in `msg_content` but the raw tool data is gone. If the LLM needs the raw data again, it can re-call the tool.
- Designing a "session continuity" feature for any future Mavis version: the SessionStart/UserPromptSubmit pair is the working pattern. Don't try to inject context via persona system-prompt edits — runtime hooks are the right layer.

### 2026-08-30: `liveness_ping_failed` events in `liveness_crash.jsonl` are FALSE-POSITIVE crash signals (self-recovering)

**Rule**: When you see an entry like
```json
{"ts": "...", "event": "crash", "reason": "liveness_ping_failed: [Errno 13] Permission denied: 'data_cache\\liveness.tmp'", "uptime_sec": 192617.83, "last_ping_age_sec": 30.5, "main_thread_alive": true, ...}
```
in `data_cache/liveness_crash.jsonl`, **do NOT restart the bot**. The `main_thread_alive: true` field is the discriminator. The liveness thread caught its OWN `tmp.write_text()` exception at `kotak_bot/utils/liveness.py:201` via the `except Exception` at line 166-175, wrote a "crash" event with the traceback, then the next 30s ping succeeded and the bot kept running.

**Evidence (2026-08-30 02:00:39 IST)**: A `liveness_ping_failed: [Errno 13] Permission denied: 'data_cache\\liveness.tmp'` event was written for PID 10544 at uptime 192617s (53.5h). The bot kept running for another 21+ hours after that, still PID 10544 at the time of writing (uptime ~268000s = 74.3h). No restart, no Telegram, no real impact. Previous instance: 2026-08-24 03:20:50 with `OSError: [Errno 22] Invalid argument: 'data_cache\\liveness.tmp'` for PID 15204 (uptime 103109s) — same pattern, also self-recovered.

**Root cause**: `kotak_bot/utils/liveness.py:200-207` writes to `data_cache/liveness.tmp` and then `os.replace`s it onto `liveness.json`. On Windows, if the previous ping's `tmp` file handle is still being released by the kernel (a known Win32 file-locking race when the writer is the same process within ~30s), the next `tmp.write_text(...)` returns `PermissionError [Errno 13]`. The fallback at line 207 (`self.ping_file.write_text(...)`) has the same vulnerability. The liveness thread's outer `try/except` was deliberately written to NEVER let the liveness thread itself die — see the comment at line 167 "Never let the liveness thread itself die". So the thread logs the failure and tries again 30s later. This is by design, not a bug.

**Apply when**:
- Reading `data_cache/liveness_crash.jsonl` and seeing `event: "crash", reason: "liveness_ping_failed:*"` — check the `main_thread_alive` field. If `true`, ignore. If `false`, treat as a real crash and follow the recovery procedure below.
- Distinguishing real crashes from false positives at a glance:
  - `event: "atexit", reason: "atexit_normal"` → process exited cleanly (could be a planned restart, could be NSSM stopping it)
  - `event: "atexit", reason: "signal:SIGINT"` / `"signal:SIGBREAK"` → external kill (NSSM stop, taskkill, Ctrl+C)
  - `event: "signal", reason: "SIGINT"` / `"SIGBREAK"` / `"SIGTERM"` → signal handler fired (planned shutdown)
  - `event: "crash", main_thread_alive: true` → liveness sub-component hiccup, **NOT a real crash**
  - `event: "crash", main_thread_alive: false` → real process death, follow recovery
- For liveness state, trust `data_cache/liveness.json` (rewritten every 30s by the ping thread) and `data_cache/heartbeat_latest.json`. `age_sec < 60` = healthy. Do not use `liveness_crash.jsonl` for liveness state — it's an event log, not a status file.
- If the false-positive noise becomes annoying: future hardening is `tmp.unlink(missing_ok=True)` before `tmp.write_text(...)` at liveness.py:201, and using `os.replace(self.ping_file, tmp)` (reverse direction) so the tmp is always the new file. Out of scope for this nightly — the spec says "Do NOT touch kotak_bot/ core code" and `kotak_bot/utils/liveness.py` is core.
- Operators (and future crons) writing alerts on `liveness_crash.jsonl` should filter: only alert on `event: "crash"` AND `main_thread_alive: false`. The current `kotak-bot-watchdog` cron correctly uses `liveness.json` `age_sec` and is not affected.

## Production-level utilities (added 2026-08-23 + 2026-08-24)

### Round 1 (commit 4188b8d, 2026-08-23 13:32 IST)

Three new utilities in `kotak_bot/utils/` plus their unit tests and a
pre-market smoke test in `scripts/`. They are wired into the existing
8:25 daily-maintenance cron (`kotak-bot-daily-maintenance`) as a new
**smoke test step** that gates "ready for market open" before the
existing re-auth and Telegram summary.

Three new utilities in `kotak_bot/utils/` plus their unit tests and a
pre-market smoke test in `scripts/`. They are wired into the existing
8:25 daily-maintenance cron (`kotak-bot-daily-maintenance`) as a new
**smoke test step** that gates "ready for market open" before the
existing re-auth and Telegram summary.

### `kotak_bot/utils/structured_log.py` — JSON logger
- Replaces the verbose human-readable loguru output for in-process events
  with a structured JSON stream at `data_cache/runtime.jsonl` (rotated 10MB×5).
- Every line is one JSON object with envelope: `ts`, `level`, `logger`,
  `msg`, `module`, `func`, `line`, `pid`, `thread`. Custom fields attached
  via `logger.info("...", extra={"k": v})` are FLATTENED into the top-level
  JSON (queryable, not nested).
- Public API: `configure()`, `get_logger()`, `log_event(level, event, **fields)`,
  `@log_call("name")` decorator.
- Test: `tests/test_structured_log.py` — 7 tests, all pass.

### `kotak_bot/utils/circuit_breaker.py` — circuit breaker
- Three states: CLOSED (normal) → OPEN (fail-fast) → HALF_OPEN (one probe)
  → CLOSED. Trips on EITHER consecutive-failure threshold OR error-rate
  threshold within a sliding window.
- Public API: `CircuitBreaker(name, fail_threshold, error_rate_threshold,
  cooldown_sec, window_sec)`, `cb.call(fn, *args)`, `cb.snapshot()`,
  `cb.reset()`. `get_or_create("name")` returns a process-wide singleton.
- Test: `tests/test_circuit_breaker.py` — 11 tests, all pass.

### `kotak_bot/utils/metrics.py` — in-process metrics
- Counters, gauges, timings with optional tag dimensions. Sliding cap
  per key (2000) to bound memory in long-running processes.
- Public API: `metric_inc()`, `metric_gauge()`, `metric_timing()`,
  `snapshot()` → dict, `to_prometheus_text()` for sidecar scraping,
  `write_jsonl(path)` for time-series persistence.
- **CRITICAL BUG FIX**: original `_LOCK = threading.Lock()` caused deadlock
  when `write_jsonl()` (holds the lock) called `snapshot()` (also acquires
  the lock). FIXED by using `threading.RLock()`. See commit history.
- Test: `tests/test_metrics.py` — 10 tests, all pass.

### `scripts/pre_market_smoke_test.py` — readiness gate
- 11 checks: 7 CRITICAL (liveness, NSSM bot, NSSM dashboard, dashboard HTTP,
  market-open-today, paper state capital, credentials) + 4 WARNING
  (self_audit anomalies, log_clean, scrip_master age, orphan python procs).
- Exit codes: 0 = OK, 1 = CRITICAL (do not trade), 2 = WARN only.
- Run: `python scripts/pre_market_smoke_test.py [--json] [--tg]`.
- Integrated into `scripts/daily_maintenance.py` as step 3.5 — runs after
  the 8-check self_test and before Kotak re-auth, so we fail FAST and
  cleanly before issuing any re-auth requests.

## Test suite state (2026-08-24 01:25 IST)
- **297 tests pass, 0 fail, 16.90s** (`pytest tests/`)
- Round 1 (commit 4188b8d): 260 tests, 7 new (structured_log, circuit_breaker, metrics).
- Round 2 (this commit): 297 tests, +37 new (shutdown, retry, audit, http_server, http_watchdog).

## Orphan-process hygiene (2026-08-23 13:10 IST)
- 9 processes >2h old killed: 2 kite-mcp.exe orphans (10484, 11676) +
  1 old powershell (7944). 7 career-pipeline workers (1716, 3628, etc.)
  intentionally LEFT ALIVE — they have their own watchdog and are a
  different project's responsibility.
- Pattern: `Start-Process -Verb RunAs -FilePath powershell -ArgumentList
  -NoProfile, -ExecutionPolicy, Bypass, -File, $script` then
  `Stop-Process -Id $pid -Force` for each target.
- NSSM auto-restarted the bot (PID 15204) after the orphan cleanup —
  it runs with the FIXED liveness code (`realized_pnl` from broker margins,
  not `risk.state.realized_pnl`).

## Uncommitted second-batch utilities (2026-08-23 14:00 IST)
- At 13:48-14:03 IST, between the orphan cleanup (13:11-13:54) and the
  compliance-PDF generation (15:30), 9 production files were added but
  never committed. They form a coherent "second batch" of utilities
  parallel to the morning's first batch (structured_log / circuit_breaker
  / metrics + pre_market_smoke_test, which IS committed as `4188b8d`):
  - `kotak_bot/http_server.py` (227 lines) — stdlib HTTP server exposing
    `/health`, `/metrics`, `/status` on :8502
  - `kotak_bot/utils/audit.py` (193 lines) — JSONL audit log for
    trading decisions (open/close/hold/skip with rationale + fields)
  - `kotak_bot/utils/retry.py` (172 lines) — exponential backoff +
    jitter retry helper with `NonRetriableError` short-circuit
  - `kotak_bot/utils/shutdown.py` (184 lines) — graceful SIGTERM/SIGINT
    handler with LIFO callbacks and `wait_for_drain(timeout)`
  - `system/run_http_server.ps1` (70 lines) — NSSM entry point for
    `KotakHttpServer` Windows service
  - `tests/test_audit.py`, `test_http_server.py`, `test_retry.py`,
    `test_shutdown.py` (513 lines total) — unit tests for each
  - Status: `git status` shows them as untracked, `git log` returns empty
    for these paths — they've NEVER been committed. They look complete
    and self-consistent (docstrings + tests + NSSM wiring), but the
    user has not yet reviewed them.
- **Apply when**:
  - The nightly-improvement cron's spec says `git add -A && git commit
    -m "docs: nightly improvement - ..."` — running that command today
    would commit ALL of these untracked production files together with
    any AGENTS.md change. That mixes a docs-only nightly improvement
    with a ~1,400-line feature drop. **DO NOT use `git add -A` on days
    when these files are untracked.** Use a targeted `git add AGENTS.md`
    (or whatever single docs path you changed) instead. Then surface the
    uncommitted-batch state to the user.
  - If the user asks "what's in the working tree that's not committed?",
    these 9 files are the answer. Suggest the user review + commit
    them as one or more logical commits (probably split utils vs.
    http_server+service since they have different blast radius).
  - The `system/run_http_server.ps1` will need a matching NSSM
    `KotakHttpServer` service registration step (see its header comment
    — `sc.exe create ... binPath=`) before it can be used.
- **Related secondary finding (same window)**: the self-monitor's
  anomaly detector fired `telegram_sent=True` at 13:15:28 IST for
  "new crash within last hour: atexit_normal pid=16872". That PID was
  one of the intentional orphan kills from the 13:11-13:54 cleanup —
  the atexit was expected, the Telegram was a false alert. A second
  similar anomaly fired at 13:30:12 IST (pid=20316) but Telegram was
  throttled. **Future improvement**: have the self-monitor skip
  `atexit_normal` events for PIDs that died during the
  orphan-cleanup window (would need a known-cleanup PIDs allowlist
  sourced from the cleanup script). Not done in this nightly pass.

### Round 2 (2026-08-24 01:25 IST) — graceful shutdown, retry, audit, HTTP server

Four new utilities + a production HTTP server + a watchdog. Total
+37 tests, **297 tests pass, 0 fail**.

#### `kotak_bot/utils/shutdown.py` — GracefulShutdown
- Process-wide singleton that catches SIGTERM/SIGINT/SIGBREAK and runs
  drain callbacks in LIFO order (like a Go `defer` stack).
- `register_drain_callback(fn, name="...")` — returns an unregister handle.
- `request_shutdown(reason)` is idempotent.
- `run_with_shutdown(main_fn)` — runs main_fn in a thread; signal handlers
  in main thread; on signal, request_shutdown and wait for main_fn to
  finish (bounded by `drain_timeout_sec`).
- A failing callback does NOT block subsequent callbacks.
- Test: `tests/test_shutdown.py` — 7 tests.

#### `kotak_bot/utils/retry.py` — exponential backoff with jitter
- `retry_with_backoff(fn, *args, max_attempts=3, base_sec=1.0, max_sec=30.0, factor=2.0, retriable=None, on_retry=None)`
- Decorator form: `@retry(max_attempts=3, retriable=(ConnectionError,))`.
- `RetriableError` / `NonRetriableError` base classes for "is this worth retrying?"
- Jitter: ±25% of the computed delay. Capped at `max_sec`.
- `retriable=` accepts either a tuple of exception types OR a predicate.
- Test: `tests/test_retry.py` — 9 tests.

#### `kotak_bot/utils/audit.py` — AuditLog
- Append-only JSONL with structured fields. Auto-rotation at `max_bytes`.
- `record(event, **fields)`, `tail(n)`, `query(event=, since=, until=, **filters)`, `summary()`.
- Thread-safe under concurrent writers (verified by test).
- `summary()` returns `{total, by_event, by_symbol, first_ts, last_ts, size_bytes}`.
- Test: `tests/test_audit.py` — 8 tests.

#### `kotak_bot/http_server.py` — stdlib HTTP server
- Exposes `/health` (200 ok / 503 degraded), `/metrics` (Prometheus text),
  `/status` (JSON dump: liveness, paper_state, audit, metrics, circuit_breakers).
- Uses stdlib only (`http.server.ThreadingHTTPServer`) — no new dependency.
- `python -m kotak_bot.http_server --port 8502` to run as a sidecar.
- BUG FIX DURING TEST: `_read_liveness()` was returning the raw data dict
  without setting `available: True` on the success path. Now returns
  `{"available": True, "age_sec": ..., **data}`. Caught by live probe.
- Test: `tests/test_http_server.py` — 6 tests.

#### `scripts/http_server_watchdog.py` + `system/run_http_server.ps1`
- Watchdog checks if HTTP server is responding on :8502 every 5 min
  during market hours (cron `kotak-http-watchdog`, `*/5 9-15 * * 1-5`).
- If not, restarts via `Start-Process -WindowStyle Hidden`. Appends a
  one-line record to `data_cache/http_watchdog.jsonl` for history.
- Run: `python scripts/http_server_watchdog.py --port 8502`
- Test: `tests/test_http_watchdog.py` — 7 tests.

#### Why the HTTP server isn't a Windows service (NSSM/sc.exe)
- We tried both NSSM and sc.exe to register KotakHttpServer as a Windows
  service. Both failed because the powershell-script-as-service pattern
  doesn't register a proper ServiceMain callback within 30s, so Windows
  kills the service with Event 7000/7009 timeout.
- **Chosen production approach**: run the python process detached via
  `Start-Process` (Start-Process -WindowStyle Hidden -PassThru), and
  rely on the `kotak-http-watchdog` cron to keep it alive. This is a
  standard "supervisor" pattern (systemd's `Restart=always` analog).
- Trade-off: if the whole host reboots, the HTTP server doesn't auto-start.
  Fix for production: add a Windows Task Scheduler entry on User Logon
  that launches `system/run_http_server.ps1`. Not done in this pass.

#### Bug fixed: stale `_test_*.jsonl` files were being committed
- Tests for `structured_log` and `metrics` write to `data_cache/_test_*.jsonl`.
- Added `data_cache/_test_*.jsonl` and `data_cache/_test_*.json` to .gitignore.
- Also added: `data_cache/compliance/`, `data_cache/http_watchdog.jsonl`,
  `Logs/http_server_*.log`, `Logs/http_server.heartbeat`.

## Monday 2026-08-24 readiness — verified 01:25 IST
- NSSM `KotakBotPaper` (PID 15204) + `KotakDashboard` (PID 15780): both Running, Automatic.
- Dashboard :8501: HTTP 200.
- HTTP :8502 /health: HTTP 200, liveness 10.8s old, `state=running`, `provider_error=''`.
- Pre-market smoke test: 6/7 CRITICAL pass + 1 WARNING (log_clean with 2 historical tracebacks, scrip_master not loaded — both expected for fresh week). `market.open_today` correctly identifies Monday.
- Self-monitor: OK, 0 anomalies, liveness 19.9s old.
- Paper state: cash=Rs.100,000, realized=Rs.0, preserved across weekend.
- 297 tests pass in 16.9s.
- All Monday-relevant crons scheduled and will fire: 08:15 morning-brief, 08:25 daily-maintenance (with new smoke test step), 09:00 daily-status + trader-desk first tick, 09:00-15:30 trader-desk every 5 min, 09:00-15:30 http-watchdog every 5 min, 15:35 eod-report, 15:45 state-backup.

## 2026-08-26 23:00 IST — heartbeat-next-tick cron was silently dying on context-compaction

**Rule**: The `heartbeat-next-tick` cron (cronId `d9fdcd69-b4e0-4f88-8368-7b4ab52f841c`,
every 5 min, **AGENTS.md previously called it `kotak-bot-heartbeat` —
the canonical name in the cron registry is `heartbeat-next-tick`**)
was binding to a single long-lived session
(`sessionId: mvs_d36c7630216c4768b73eb11633c4be10`) with a ~5 KB
prompt. After ~300+ ticks of accumulation, the per-turn state grew
past the runtime's checkpoint budget, and every subsequent tick
aborted with:
```
compaction_failed: Context is too large for checkpoint generation
                   after one temporary whole tool trim.
```
The user prompt never even reached the LLM — the runtime died at
the pre-turn checkpoint stage. Three consecutive observed
failures: 2026-08-24 18:20 IST (turn 312), 2026-08-25 07:30 IST
(turn 306), 2026-08-26 23:00 IST (turn #N — fresh prompt but
reused session still has full history). The 23:00 self-audit was
the trigger that surfaced this.

**The session-list view** shows these sessions with
`status.type = "error"` and
`status.message = "before_llm_checkpoint_aborted: context_compaction_failed:..."`.
A "fresh" cron tick can still hit this if the session is
`mode: sessionId` AND has accumulated enough prior turns.

**Evidence** that the bot was actually fine during this entire
window: self-monitor's `data_cache/self_audit.jsonl` shows
liveness fresh, log fresh, dash=200 throughout. The
`kotak-bot-247-watchdog` cron was the only safety net during
this period; the 5-min "smart" heartbeat that knows about
dashboard restart + Telegram was effectively dead.

**Fix shipped 2026-08-26 23:08 IST** (this nightly-improvement
pass — commit pending):
1. New `scripts/heartbeat.py` (~280 lines, stdlib + `psutil` +
   `httpx`) does the 5 checks **deterministically** — bot
   process count (4h window + unfiltered second check),
   dashboard HTTP 200, log freshness, restart bot (market hours
   only, 09:00-15:30 IST Mon-Fri), restart dashboard
   (anytime), Telegram on restart with 30-min cooldown, JSONL
   history at `data_cache/heartbeat_history.jsonl` (rotated at
   720 records = 60 h of 5-min ticks), one-line stdout for cron
   log. Uses the **canonical `Logs\bot_stderr.log` path** (the
   NSSM-managed one) — fixes the vestigial-root-file bug from
   2026-08-22 by making the path a code constant, not a
   per-prompt string the LLM might re-introduce.
2. Cron prompt reduced from ~5 KB / 6 step blocks to a single
   line: "Run the heartbeat.py script, report its stdout." The
   LLM is now a thin shell, not the brain.
3. Cron `session` binding changed from
   `mode: sessionId → mvs_d36c7630...` to `mode: new` —
   each tick is a fresh session, so per-tick state can never
   accumulate past the checkpoint budget. No state needed
   anyway; the script writes the durable record to
   `data_cache/heartbeat_history.jsonl`.

**Apply when**:
- Diagnosing "why does my 5-min cron suddenly fail with
  `context_compaction_failed`?" — check the session binding.
  `mode: sessionId` reuses a long-lived session, which grows
  with every turn. Switch to `mode: new` for stateless periodic
  jobs. This applies to any cron that is "just run this command
  and report", not just the heartbeat.
- The user prompt's size matters less than the session's
  accumulated turns. A 200-byte prompt in a 300-turn session
  will still fail compaction; a 5 KB prompt in `mode: new` will
  not.
- For ANY cron that does significant work (reads files, calls
  MCP, runs scripts), prefer the "script-driven" pattern: put
  the logic in `scripts/`, keep the cron prompt to 1-3 lines
  that just invoke the script. This isolates the LLM cost to
  a thin shell and makes the actual work testable, versioned,
  and reviewable.
- When you see `status.type = "error"` with the
  `before_llm_checkpoint_aborted` message in the session
  list, the session is permanently poisoned. Don't bother
  trying to recover it — change the cron to `mode: new` (or a
  different `sessionId`) to start clean.

## http_server_watchdog design gap (2026-08-27 12:20 IST)

`scripts/http_server_watchdog.py` has a **DEGRADED-without-restart**
hole: it only auto-restarts the HTTP server when `is_listening()`
returns False (port unbound). If the http_server process is hung
but the listening socket is still up (kernel hasn't reaped the
FD), `is_listening` returns True and the watchdog skips the
restart branch — it goes straight to `probe_health()`, which
times out and returns exit 1. The Telegram alert fires but the
bot stays broken.

Observed 2026-08-27 12:20 IST: last OK at 12:15:16 (PID 16228,
age 23.9s, healthy), then `http 0 body=error: timed out` at
12:20:29. Port :8502 was still bound by the hung process, so the
watchdog reported DEGRADED but didn't restart.

**Workaround applied by the cron tick** (until the script is
fixed): when watchdog exits non-zero AND `http 0` AND the port
is bound by a stale python PID, the tick does the restart
manually:
1. `Get-NetTCPConnection -LocalPort 8502 -State Listen` to find
   the hung OwningProcess.
2. `Stop-Process -Force` on that PID (use `$procId`, not `$pid`
   — `$pid` is read-only in PowerShell).
3. `Start-Process` the http_server module via
   `python -u -m kotak_bot.http_server --port 8502` with
   `-RedirectStandardOutput Logs\http_server.out` and
   `-RedirectStandardError Logs\http_server.err`,
   `-WindowStyle Hidden -PassThru`.
4. `Start-Sleep 5`, then re-run
   `scripts\http_server_watchdog.py --port 8502 --dry-run` to
   confirm `/health = 200`.

**Apply when**:
- `http_server_watchdog.py` exits 1 with `http 0 body=error: timed out`
  and a stale PID still owns :8502. The script's restart branch
  is dead code in this state — escalate to manual force-restart.
- The proper fix is in the script: when `is_listening()` returns
  True but `probe_health()` returns False with a connection
  error, the script should also call `restart_server()`. Don't
  depend on the kernel to reap a hung-but-listening socket.
- Note also: when invoked from a single chained PowerShell, the
  watchdog call can hang past 60s if the http_server start races
  with the bind. Wait 5s post-`Start-Process` before re-probing.

### 2026-08-29: Legacy `kotak-bot-heartbeat` cron disabled — it was duplicating `heartbeat-next-tick` and reading the wrong log file

**Rule**: The legacy `kotak-bot-heartbeat` cron (cronId
`3fc44c8d-b1e2-4606-9812-d7b9cec0f78e`, `*/5 * * * *`) was the
2026-08-22-era LLM-based heartbeat with the documented vestigial-log
bug (its `Select-String` path pointed at the lowercase root
`bot_stderr.log`, NOT the canonical `Logs\bot_stderr.log`). On
2026-08-26 we shipped `heartbeat-next-tick` (cronId
`d9fdcd69-...`, runs `scripts/heartbeat.py` deterministically) as
the replacement — but the legacy cron was never disabled. Result
between 2026-08-26 and 2026-08-29: two 5-min crons both firing on
the same machine, with `heartbeat-next-tick` doing the real work
and `kotak-bot-heartbeat` doing the wrong-but-silent
vestigial-file read, ~288 redundant LLM calls/day.

**Evidence (2026-08-29 23:00)**: `mavis session list` at 23:00 IST
showed `kotak-bot-heartbeat · 08-29 23:00` AND
`heartbeat-next-tick · 08-29 23:00` as separate cron sessions,
both with `mode: new` and `status: started`/`idle`. The legacy
prompt is the one with `Select-String -Path
'C:\Users\saini\...kotak-neo-bot\bot_stderr.log'` (lowercase
root, frozen since 2026-08-20 02:27:15) — see the 2026-08-22
entry above for the full pathology. The `heartbeat-next-tick`
prompt is the single-line `Run:
C:\...\scripts\heartbeat.py` (3-line `mode: new` shell that
delegates everything to the deterministic script).

**Fix shipped 2026-08-29 23:00 IST** (this nightly-improvement
pass): `mavis cron update --cronId 3fc44c8d-... --enabled false`.
The cron is now `enabled: false, status: paused` (verified via
`mavis cron get`). The registry keeps the prompt body for audit
history; future `mavis cron list` will show it disabled. The
`heartbeat-next-tick` cron is unchanged (it's the one doing real
work). Net effect: ~288 fewer LLM turns/day and the vestigial-log
footgun is removed from production.

**Why not delete the cron?** Keeping a disabled cron entry
preserves the audit trail (you can `cron get` to read the legacy
prompt and see what the bug was). If we ever need to revert, it's
a one-flag toggle. Don't `cron delete` it.

**Apply when**:
- Auditing the cron stack: `kotak-bot-heartbeat` should now
  show `enabled: false, status: paused` in `mavis cron list`.
  If a future agent sees it enabled, that's a regression.
- Adding NEW heartbeat-style crons: use the `heartbeat-next-tick`
  pattern (one-line `mode: new` prompt that runs
  `scripts/heartbeat.py`). Do NOT re-introduce a
  multi-paragraph LLM-driven prompt — that's the bug class this
  entry closes.
- A similar duplicate-cron pattern may exist for other
  5-min crons (e.g. `kotak-bot-watchdog` cronId `a747781e-...`
  is ALSO LLM-based, also runs every 5 min Mon-Sat, ALSO reads
  the lowercase root `bot_stderr.log`). The 24/7 watchdog
  (`kotak-bot-247-watchdog`, cronId `70e211c8-...`, every 15
  min) is the canonical replacement there. Cleaning that up is
  a separate change — out of scope for tonight, but a candidate
  for a future nightly pass.
- Diagnosing "why are there two 5-min heartbeat sessions in
  `session list`?" — check `mavis cron list` for any cron
  with `enabled: true, schedule: */5 * * * *`. There should be
  exactly one (the canonical `heartbeat-next-tick`).


