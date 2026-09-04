# install_daily_tasks.ps1 - install daily_autonomy.py as Windows scheduled tasks
#
# Replaces 23 paused Mavis crons + 11 in-process schedulers with 3 simple
# scheduled tasks. Each task runs the corresponding phase of daily_autonomy.py.
#
# Usage (as Administrator):
#   powershell -ExecutionPolicy Bypass -File scripts/install_daily_tasks.ps1 -Install
#   powershell -ExecutionPolicy Bypass -File scripts/install_daily_tasks.ps1 -Uninstall
#
# Times (IST):
#   08:25 IST = 02:55 UTC (IST is UTC+5:30)
#   15:30 IST = 10:00 UTC
#   23:00 IST = 17:30 UTC
#
# Note: Windows Task Scheduler uses the LOCAL clock, not UTC. If your machine is
# set to IST (which is +5:30 from UTC), use 08:25 / 15:30 / 23:00 directly.
# If your machine is in UTC, use 02:55 / 10:00 / 17:30.

param(
    [switch]$Install,
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"

$Tasks = @(
    @{
        Name = "kotak-pre-market-self-heal"
        Description = "08:25 IST: pre-market self-heal, Kotak re-auth, self-test"
        Time = "08:25"
        Args = "pre_market"
    },
    @{
        Name = "kotak-eod-pnl-evaluator"
        Description = "15:30 IST: EOD P&L evaluator, strategy perf, Telegram"
        Time = "15:30"
        Args = "eod"
    },
    @{
        Name = "kotak-nightly-state-backup"
        Description = "23:00 IST: state backup, self-test log, gate status"
        Time = "23:00"
        Args = "nightly"
    }
)

$Script = "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\.venv\Scripts\pythonw.exe"
$Arg = "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\scripts\daily_autonomy.py"

if ($Uninstall) {
    foreach ($t in $Tasks) {
        Write-Host "uninstalling $($t.Name)..."
        Unregister-ScheduledTask -TaskName $t.Name -Confirm:$false -ErrorAction SilentlyContinue
    }
    Write-Host "all tasks uninstalled"
    exit 0
}

if ($Install) {
    foreach ($t in $Tasks) {
        Write-Host "installing $($t.Name) at $($t.Time)..."
        $action = New-ScheduledTaskAction -Execute $Script -Argument "`"$Arg`" $($t.Args)""
        $trigger = New-ScheduledTaskTrigger -Daily -At $t.Time
        $settings = New-ScheduledTaskSettingsSet `
            -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries `
            -StartWhenAvailable `
            -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
        Register-ScheduledTask `
            -TaskName $t.Name `
            -Action $action `
            -Trigger $trigger `
            -Settings $settings `
            -Description $t.Description `
            -RunLevel Highest `
            -Force
        Write-Host "  installed: $($t.Name) at $($t.Time)"
    }
    Write-Host ""
    Write-Host "3 daily tasks installed."
    Write-Host "Verify with: Get-ScheduledTask | Where-Object { `$_.TaskName -like 'kotak-*' }"
    exit 0
}

Write-Host "Usage: -Install or -Uninstall"
exit 1
