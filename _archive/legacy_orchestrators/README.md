# legacy_orchestrators/

Alternate bot lifecycle / supervision implementations. Authored 2026-08-20/22
during a flurry of "let's add a self-healing layer" work. None of them were
ever wired into the live NSSM launch path or the cron watchdog.

## Files

- `kotak_healer.py` — proposed "self-healing watchdog" that restarts the bot
  if it dies. Superseded by the NSSM `KotakBotPaper` service (which has built-in
  restart on crash) + the `kotak-bot-watchdog` cron.
- `kotak_orchestrator.py` — proposed orchestrator that runs healer + supervisor
  + executor in coordination. Never finished; current loop is just NSSM.
- `kotak_supervisor.py` — proposed long-running supervisor. Same as above.
- `kotak_watchdog.py` — proposed watchdog. Same as above.
- `kotak_executor.py` — proposed execution wrapper. The live execution path
  is `kotak_bot.execution.order_manager.OrderManager`.
- `start_24x7_daemons.ps1` — proposed all-in-one launcher. NSSM does this.
- `start_autonomous.ps1` — same.
- `send_eod_report.py` — alternate EOD report. The live one is `kotak-bot-state-backup`
  cron which runs `scripts/daily_state_backup.py`.

## How to verify these are dead

```powershell
# Should return nothing
Get-ChildItem 'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot' `
    -Recurse -Include *.py,*.ps1,*.md,*.txt,*.yaml,*.yml,*.json -File |
    Where-Object { $_.FullName -notmatch '_archive' } |
    Select-String -Pattern 'kotak_healer|kotak_orchestrator|kotak_supervisor|kotak_watchdog|kotak_executor|start_24x7|start_autonomous|send_eod_report'
```

If that returns matches, someone has re-introduced a reference. Investigate
before deleting this directory.
