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

Write-LoopLog "supervisor_loop: starting wrapper (pid=$PID)"

while ($true) {
    if (Test-SupervisorAlive) {
        # Supervisor already healthy, just wait and re-check
        Start-Sleep -Seconds 30
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
