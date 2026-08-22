# _archive

Code that was once in active rotation but is no longer wired into the running
system. Kept for forensic / historical reference only.

## Directory layout

- `legacy_orchestrators/` — alternate bot orchestrators (healer, watchdog,
  supervisor, orchestrator, executor) and their start scripts + the old
  `send_eod_report.py`. The official bot lifecycle is managed by NSSM
  (`system\run_bot.ps1`) plus the `kotak-bot-watchdog` cron. None of these
  files are imported by `kotak_bot/`, the cron prompts, or the NSSM
  launch path.

## What is NOT in here (and why)

- `kotak_brain.py` (root) — ACTIVE. Imported by `scripts/trader_state.py`
  (the trader-desk cron reads it to build the LLM context).
- `mavis_app_loop.ps1` + `mavis_app_wrapper.vbs` (root) — ACTIVE. Mavis UI
  re-launcher, runs hidden at user logon via the .vbs shim.
- `supervisor_loop.ps1` + `supervisor_wrapper.vbs` (root) — ACTIVE.
  Supervisor re-launcher, runs hidden at user logon via the .vbs shim.
- `verify_reset.py` (root) — utility, harmless to keep.

## When to delete this directory

Once the legacy orchestrators have been confirmed dead for ≥30 days
(no new edits, no imports, no NSSM/cron references), the entire
`_archive/` tree can be removed. Until then, keep it — its job is to
prevent the "didn't we have a watchdog for that?" archeology.
