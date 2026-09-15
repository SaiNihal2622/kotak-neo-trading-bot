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
# FIX 2026-09-04 15:25: was failing to register tasks because of:
#   1. Quoting bug in -Argument (concatenated $Arg and $t.Args without space)
#   2. Using pythonw.exe (no console) instead of python.exe for better logging
#   3. -Force flag missing (so re-runs would fail)
#   4. No Read-Host at end, so window closed before user could see result

param(
    [switch]$Install,
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"

# Use python.exe (not pythonw.exe) so any stdout shows in scheduled task logs
$Script = "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\.venv\Scripts\python.exe"
$ScriptDir = "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot"

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

if ($Uninstall) {
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "Uninstalling kotak-neo-bot daily tasks"
    Write-Host "========================================" -ForegroundColor Cyan
    foreach ($t in $Tasks) {
        Write-Host "  uninstalling $($t.Name)..." -ForegroundColor Yellow
        $exists = Get-ScheduledTask -TaskName $t.Name -ErrorAction SilentlyContinue
        if ($exists) {
            Unregister-ScheduledTask -TaskName $t.Name -Confirm:$false
            Write-Host "    removed" -ForegroundColor Green
        } else {
            Write-Host "    not installed" -ForegroundColor Gray
        }
    }
    Write-Host ""
    Write-Host "All tasks removed." -ForegroundColor Green
    Write-Host "Press Enter to close"
    Read-Host
    exit 0
}

if ($Install) {
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "Installing kotak-neo-bot daily tasks (FIX 2026-09-04)"
    Write-Host "========================================" -ForegroundColor Cyan

    # Verify admin
    $isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $isAdmin) {
        Write-Host "ERROR: This script must be run as Administrator." -ForegroundColor Red
        Write-Host "Right-click INSTALL.bat -> Run as administrator" -ForegroundColor Yellow
        Read-Host
        exit 1
    }
    Write-Host "  Running as Administrator: OK" -ForegroundColor Green

    # Check daily_autonomy.py exists
    $autonomyPath = Join-Path $ScriptDir "scripts\daily_autonomy.py"
    if (-not (Test-Path $autonomyPath)) {
        Write-Host "ERROR: $autonomyPath not found" -ForegroundColor Red
        Read-Host
        exit 1
    }
    Write-Host "  daily_autonomy.py: OK" -ForegroundColor Green

    foreach ($t in $Tasks) {
        Write-Host "  installing $($t.Name) at $($t.Time)..." -ForegroundColor Yellow
        try {
            # FIX 2026-09-04 15:25: pass arguments as SEPARATE items in array, not concatenated string
            $action = New-ScheduledTaskAction `
                -Execute $Script `
                -Argument @($autonomyPath, $t.Args) `
                -WorkingDirectory $ScriptDir
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
                -Force `
                -ErrorAction Stop
            Write-Host "    installed at $($t.Time) IST" -ForegroundColor Green
        } catch {
            Write-Host "    FAILED: $_" -ForegroundColor Red
        }
    }

    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "Verification:" -ForegroundColor Cyan
    Get-ScheduledTask | Where-Object { $_.TaskName -like "kotak-*" } | Select-Object TaskName, State, @{N='Time';E={if ($_.Triggers) { $_.Triggers[0].CimInstanceProperties | Where-Object { $_.Name -eq 'StartBoundary' } | Select-Object -ExpandProperty Value } else { 'n/a' }} } | Format-Table -AutoSize
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "Done. 3 daily tasks should be installed." -ForegroundColor Green
    Write-Host "Press Enter to close"
    Read-Host
    exit 0
}

Write-Host "Usage: -Install or -Uninstall"
Read-Host
exit 1
