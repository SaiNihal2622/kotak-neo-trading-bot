# start_autonomous.ps1
# One-click launch for the autonomous system.
# Starts: kotak_bot (paper) + kotak_healer + kotak_brain (via orchestrator)
#
# Usage (from PowerShell):
#   .\start_autonomous.ps1
#
# This script is idempotent — it will not start a second copy of any component.

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$venvPy = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) { $venvPy = "python" }

function Get-ProcessIdByFragment([string]$fragment) {
    $pids = @()
    $procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue
    foreach ($p in $procs) {
        if ($p.CommandLine -and $p.CommandLine -like "*$fragment*") {
            if ($p.CommandLine -notlike "*start_autonomous*") {
                $pids += $p.ProcessId
            }
        }
    }
    return $pids
}

Write-Host "[autonomous] project root: $root" -ForegroundColor Cyan

# 1. kotak_bot paper
$botPids = Get-ProcessIdByFragment "kotak_bot"
if ($botPids.Count -eq 0) {
    Write-Host "[autonomous] starting kotak_bot paper..." -ForegroundColor Yellow
    $startScript = Join-Path $root "start_bot_detached.ps1"
    if (Test-Path $startScript) {
        & powershell -NoProfile -ExecutionPolicy Bypass -File $startScript
    } else {
        Write-Host "[autonomous] start_bot_detached.ps1 not found, skipping" -ForegroundColor Red
    }
} else {
    Write-Host "[autonomous] kotak_bot already running (pids: $($botPids -join ','))" -ForegroundColor Green
}

# 2. kotak_healer (long-running, --once is just the check)
$healerPids = Get-ProcessIdByFragment "kotak_healer"
if ($healerPids.Count -eq 0) {
    Write-Host "[autonomous] starting kotak_healer..." -ForegroundColor Yellow
    $healerArgs = @("-NoProfile","-ExecutionPolicy","Bypass","-Command",
        "Start-Process -WindowStyle Hidden -FilePath '$venvPy' -ArgumentList '$(Join-Path $root 'kotak_healer.py')' -RedirectStandardOutput '$(Join-Path $root 'data_cache\healer_stdout.log')' -RedirectStandardError '$(Join-Path $root 'data_cache\healer_stderr.log')'")
    Start-Process -FilePath "powershell" -ArgumentList $healerArgs -WindowStyle Hidden
    Start-Sleep -Seconds 2
} else {
    Write-Host "[autonomous] kotak_healer already running (pids: $($healerPids -join ','))" -ForegroundColor Green
}

# 3. kotak_brain (one tick, then it will be re-triggered by orchestrator cron)
Write-Host "[autonomous] running kotak_brain --once..." -ForegroundColor Yellow
& $venvPy (Join-Path $root "kotak_brain.py") --once
if ($LASTEXITCODE -eq 0) {
    Write-Host "[autonomous] brain --once ok" -ForegroundColor Green
} else {
    Write-Host "[autonomous] brain --once exited $LASTEXITCODE" -ForegroundColor Red
}

Write-Host ""
Write-Host "[autonomous] ============================================" -ForegroundColor Cyan
Write-Host "[autonomous] System is up. Components:" -ForegroundColor Cyan
Write-Host "[autonomous]   - kotak_bot paper  (live trading engine)" -ForegroundColor White
Write-Host "[autonomous]   - kotak_healer     (self-healing watchdog, checks every 60s)" -ForegroundColor White
Write-Host "[autonomous]   - kotak_brain      (LLM decision engine, runs every 15 min via cron)" -ForegroundColor White
Write-Host "[autonomous]" -ForegroundColor Cyan
Write-Host "[autonomous] To check status:    python kotak_healer.py --once" -ForegroundColor White
Write-Host "[autonomous] To force re-eval:  python kotak_brain.py --once" -ForegroundColor White
Write-Host "[autonomous] Latest LLM bias:   cat data_cache\brain_state.json" -ForegroundColor White
Write-Host "[autonomous] Health:            cat data_cache\healer_state.json" -ForegroundColor White
Write-Host "[autonomous] ============================================" -ForegroundColor Cyan
