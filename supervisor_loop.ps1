# supervisor_loop.ps1
# Indefinite re-launcher for kotak_supervisor.py.
# If the supervisor dies for any reason, this loop waits 5s and starts it again.
# This is the "process resurrection" layer for non-admin Windows.
# Run with hidden window via supervisor_wrapper.vbs at user logon.

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$venvPy = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) { $venvPy = "python" }

$logDir = Join-Path $root "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$loopLog = Join-Path $logDir "supervisor_loop.log"
$supPidFile = Join-Path $root "data_cache\supervisor.pid"

function Write-LoopLog([string]$msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "[$ts] $msg" | Out-File -FilePath $loopLog -Append -Encoding utf8
}

# Cached check: is kotak_supervisor.py present at project root?
# As of 2026-08-31, the bot lifecycle is managed by NSSM services
# (KotakBotPaper / KotakDashboard / KotakHttpServer) plus watchdog.ps1;
# kotak_supervisor.py was moved to _archive\legacy_orchestrators\.
# If the file is missing, back off for $missingBackoffSec instead of
# spinning every 5s (which used to generate ~3MB/day of noise).
$missingBackoffSec = 3600
$supervisorScript = Join-Path $root "kotak_supervisor.py"
$missingLoggedAt = $null

function Test-SupervisorAlive {
    # Check if a supervisor is already running by looking at its pidfile
    if (-not (Test-Path $supPidFile)) { return $false }
    try {
        $pid_ = [int](Get-Content $supPidFile -ErrorAction SilentlyContinue)
        if ($pid_ -le 0) { return $false }
        $proc = Get-Process -Id $pid_ -ErrorAction SilentlyContinue
        if ($null -eq $proc) { return $false }
        # Make sure it's actually our supervisor (not a recycled pid)
        $cmd = (Get-CimInstance Win32_Process -Filter "ProcessId=$pid_" -ErrorAction SilentlyContinue).CommandLine
        if ($cmd -and $cmd -like '*kotak_supervisor*') { return $true }
        return $false
    } catch {
        return $false
    }
}

function Test-SupervisorScriptPresent {
    return (Test-Path $supervisorScript)
}

Write-LoopLog "supervisor_loop: starting wrapper (pid=$PID)"

while ($true) {
    if (Test-SupervisorAlive) {
        # Supervisor already healthy, just wait and re-check
        Start-Sleep -Seconds 30
        continue
    }

    if (-not (Test-SupervisorScriptPresent)) {
        # kotak_supervisor.py is not at project root. Bot is now managed by
        # NSSM + watchdog.ps1. Back off so we don't spam the log; the
        # wrapper itself stays alive (vbs shim restarts it on reboot)
        # in case the file is restored later.
        if ($null -eq $missingLoggedAt -or ((Get-Date) - $missingLoggedAt).TotalSeconds -ge $missingBackoffSec) {
            Write-LoopLog "supervisor_loop: kotak_supervisor.py not found at $supervisorScript - bot is managed by NSSM (KotakBotPaper/KotakDashboard) + watchdog.ps1. Sleeping $missingBackoffSec s before re-check. (This is expected - do not start kotak_supervisor.py manually.)"
            $missingLoggedAt = Get-Date
        }
        Start-Sleep -Seconds $missingBackoffSec
        continue
    }

    try {
        Write-LoopLog "supervisor_loop: launching python kotak_supervisor.py"
        $proc = Start-Process -FilePath $venvPy `
                               -ArgumentList @("-u", "kotak_supervisor.py") `
                               -WorkingDirectory $root `
                               -WindowStyle Hidden `
                               -RedirectStandardOutput (Join-Path $logDir "supervisor.out.log") `
                               -RedirectStandardError (Join-Path $logDir "supervisor.err.log") `
                               -PassThru

        Write-LoopLog "supervisor_loop: launched supervisor pid=$($proc.Id), waiting for exit"
        Wait-Process -Id $proc.Id -ErrorAction SilentlyContinue
        Write-LoopLog "supervisor_loop: supervisor exited (rc=$LASTEXITCODE), checking again in 5s"
    }
    catch {
        Write-LoopLog "supervisor_loop: EXCEPTION: $_"
    }
    Start-Sleep -Seconds 5
}
