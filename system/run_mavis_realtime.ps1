# Self-respawning wrapper for mavis_realtime.py
# Solves the orphan-process reaping problem: this wrapper itself is launched
# via `cmd /c start /B` (truly detached), then watches the python child and
# respawns it on death. The wrapper is a long-lived parent, so the child
# never becomes orphaned.
#
# Use: powershell -NoProfile -ExecutionPolicy Bypass -File system\run_mavis_realtime.ps1
# Logs: logs\mavis_realtime.wrapper.log

$ErrorActionPreference = "Continue"
$root = "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot"
$py = Join-Path $root ".venv\Scripts\python.exe"
$script = "scripts\mavis_realtime.py"
$outLog = Join-Path $root "logs\mavis_realtime.out.log"
$errLog = Join-Path $root "logs\mavis_realtime.err.log"
$wrapLog = Join-Path $root "logs\mavis_realtime.wrapper.log"

function Log($msg) {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $msg"
    Write-Host $line
    try {
        Add-Content -Path $wrapLog -Value $line -ErrorAction SilentlyContinue
    } catch {}
}

Log "=== Mavis realtime wrapper started, root=$root ==="

Set-Location $root
$restartCount = 0

while ($true) {
    $restartCount++
    Log "Starting $script (restart #$restartCount)"
    $proc = Start-Process -FilePath $py -ArgumentList "-u", $script `
        -WorkingDirectory $root `
        -RedirectStandardOutput $outLog `
        -RedirectStandardError $errLog `
        -WindowStyle Hidden `
        -PassThru
    Log "Started PID $($proc.Id)"
    # Wait for the process to exit
    $proc.WaitForExit()
    $exitCode = $proc.ExitCode
    Log "Process exited code=$exitCode after restart #$restartCount, waiting 5s before respawn"
    Start-Sleep -Seconds 5
}
