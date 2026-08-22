# start_24x7_daemons.ps1
# One-click launcher for the 24/7 autonomous system.
# Starts (in supervision order, bottom-up):
#   1. kotak_supervisor  — topmost layer; restarts orchestrator/executor/bot/dashboard if dead
#   2. kotak_orchestrator — supervises healer + brain
#   3. kotak_executor    — paper trade execution
# Idempotent — checks for existing processes and PID-locks before launching.
#
# Usage: .\start_24x7_daemons.ps1
#
# For boot-time recovery, supervisor_wrapper.vbs is registered in
# $env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\
# so the supervisor comes back automatically after a reboot, which in turn
# brings up the orchestrator and executor.

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$venvPy = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) { $venvPy = "python" }

function Get-PyPidsByScript([string]$scriptName) {
    $pids = @()
    $procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue
    foreach ($p in $procs) {
        if ($p.CommandLine -and $p.CommandLine -like "*$scriptName*" -and $p.CommandLine -notlike "*start_24x7*") {
            $pids += $p.ProcessId
        }
    }
    return $pids
}

function Start-DetachedPy([string]$scriptRelPath, [string]$stdoutLog, [string]$stderrLog) {
    $stdoutAbs = Join-Path $root $stdoutLog
    $stderrAbs = Join-Path $root $stderrLog
    New-Item -ItemType Directory -Force -Path (Split-Path $stdoutAbs) | Out-Null
    New-Item -ItemType Directory -Force -Path (Split-Path $stderrAbs) | Out-Null
    $argList = @("-u", $scriptRelPath)
    Write-Host "  spawning: $venvPy $($argList -join ' ')" -ForegroundColor DarkCyan
    $proc = Start-Process -FilePath $venvPy `
                          -ArgumentList $argList `
                          -WorkingDirectory $root `
                          -RedirectStandardOutput $stdoutAbs `
                          -RedirectStandardError $stderrAbs `
                          -WindowStyle Hidden `
                          -PassThru
    return $proc
}

Write-Host "[24x7] project root: $root" -ForegroundColor Cyan

# 0. kotak_supervisor — topmost layer, started FIRST so it can adopt the rest
$supPids = Get-PyPidsByScript "kotak_supervisor"
if ($supPids.Count -gt 0) {
    Write-Host "[24x7] kotak_supervisor already up (pids: $($supPids -join ','))" -ForegroundColor Green
} else {
    Write-Host "[24x7] starting kotak_supervisor (topmost layer)..." -ForegroundColor Yellow
    $p = Start-DetachedPy "kotak_supervisor.py" "logs\supervisor.out.log" "logs\supervisor.err.log"
    Write-Host "[24x7]   launched supervisor pid=$($p.Id)" -ForegroundColor Green
    Start-Sleep -Seconds 2
}

# 1. kotak_orchestrator — supervises healer + brain
$orchPids = Get-PyPidsByScript "kotak_orchestrator"
if ($orchPids.Count -gt 0) {
    Write-Host "[24x7] kotak_orchestrator already up (pids: $($orchPids -join ','))" -ForegroundColor Green
} else {
    Write-Host "[24x7] starting kotak_orchestrator..." -ForegroundColor Yellow
    $p = Start-DetachedPy "kotak_orchestrator.py" "logs\orchestrator.out.log" "logs\orchestrator.err.log"
    Write-Host "[24x7]   launched orchestrator pid=$($p.Id)" -ForegroundColor Green
    Start-Sleep -Seconds 3
}

# 2. kotak_executor — paper trade execution engine
$execPids = Get-PyPidsByScript "kotak_executor"
if ($execPids.Count -gt 0) {
    Write-Host "[24x7] kotak_executor already up (pids: $($execPids -join ','))" -ForegroundColor Green
} else {
    Write-Host "[24x7] starting kotak_executor..." -ForegroundColor Yellow
    $p = Start-DetachedPy "kotak_executor.py" "logs\executor.out.log" "logs\executor.err.log"
    Write-Host "[24x7]   launched executor pid=$($p.Id)" -ForegroundColor Green
    Start-Sleep -Seconds 3
}

# 3. verify all are alive after launch
$supPids2  = Get-PyPidsByScript "kotak_supervisor"
$orchPids2 = Get-PyPidsByScript "kotak_orchestrator"
$execPids2 = Get-PyPidsByScript "kotak_executor"
Write-Host ""
Write-Host "[24x7] ============================================" -ForegroundColor Cyan
Write-Host "[24x7] Final state:" -ForegroundColor Cyan
Write-Host "[24x7]   supervisor  : $(if ($supPids2.Count  -gt 0) {'UP (' + ($supPids2  -join ',') + ')'} else {'DOWN'})" -ForegroundColor $(if ($supPids2.Count  -gt 0) {'Green'} else {'Red'})
Write-Host "[24x7]   orchestrator: $(if ($orchPids2.Count -gt 0) {'UP (' + ($orchPids2 -join ',') + ')'} else {'DOWN'})" -ForegroundColor $(if ($orchPids2.Count -gt 0) {'Green'} else {'Red'})
Write-Host "[24x7]   executor    : $(if ($execPids2.Count -gt 0) {'UP (' + ($execPids2 -join ',') + ')'} else {'DOWN'})" -ForegroundColor $(if ($execPids2.Count -gt 0) {'Green'} else {'Red'})
Write-Host "[24x7] ============================================" -ForegroundColor Cyan
Write-Host "[24x7] Tail logs:  Get-Content logs\supervisor.log -Wait" -ForegroundColor DarkGray
Write-Host "[24x7]            Get-Content logs\orchestrator.log -Wait" -ForegroundColor DarkGray
Write-Host "[24x7]            Get-Content logs\executor.log -Wait" -ForegroundColor DarkGray
Write-Host "[24x7] Boot recovery: supervisor_wrapper.vbs in startup folder" -ForegroundColor DarkGray
