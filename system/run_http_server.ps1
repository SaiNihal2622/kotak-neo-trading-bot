# =============================================================================
# run_http_server.ps1 — Windows service entry point for the production HTTP server.
# Invoked by Windows Service Control Manager as the service "KotakHttpServer".
# Exposes /health, /metrics, /status on :8502 for external monitoring.
#
# CRITICAL: This script MUST keep running for the service to be considered
# "Running" by Windows. If it exits, the service will be marked Stopped and
# the failure action (restart) will trigger. We therefore run python in the
# FOREGROUND (not Start-Process), and we redirect its output to a log file
# because the service's stdout isn't a console.
# =============================================================================
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'

$RepoRoot = 'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot'
$LogDir   = Join-Path $RepoRoot 'Logs'
$OutFile  = Join-Path $LogDir 'http_server_stdout.log'
$ErrFile  = Join-Path $LogDir 'http_server_stderr.log'
$HeartbeatFile = Join-Path $LogDir 'http_server.heartbeat'
$PythonExe = Join-Path $RepoRoot '.venv\Scripts\python.exe'
$Port      = if ($env:KOTAK_HTTP_PORT) { $env:KOTAK_HTTP_PORT } else { '8502' }
$EnvFile   = Join-Path $RepoRoot '.env'

# Ensure log directory exists
if (-not (Test-Path $LogDir)) {
  New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

# Rotate logs if they exceed 10MB
if ((Test-Path $OutFile) -and (Get-Item $OutFile).Length -gt 10MB) {
  Move-Item -Path $OutFile -Destination "$OutFile.prev" -Force
}
if ((Test-Path $ErrFile) -and (Get-Item $ErrFile).Length -gt 10MB) {
  Move-Item -Path $ErrFile -Destination "$ErrFile.prev" -Force
}

Set-Location $RepoRoot
$env:PYTHONUNBUFFERED = '1'
$env:DOTENV_PATH = $EnvFile
$env:PYTHONPATH = $RepoRoot
$env:KOTAK_HTTP_LOG = '1'

# Write a startup marker so we can detect service starts
$startupInfo = @{
  time = (Get-Date).ToString('o')
  pid  = $PID
  user = $env:USERNAME
  port = $Port
} | ConvertTo-Json -Compress
Set-Content -Path $HeartbeatFile -Value $startupInfo -Encoding UTF8

# Run python in the FOREGROUND. The script will block here, which keeps
# the service "Running". The service manager considers the service stopped
# only when this script process exits.
#
# FIX 2026-09-22 02:50: removed the `cmd /c` wrapper. Previously the cmd /
# c indirection worked around a stdout/pipe issue, but as of Python 3.12
# the wrap causes StartService FAILED 1053 ("did not respond in a timely
# fashion") because cmd.exe spawns and exits, leaving the python child
# orphaned and the Service Control Manager unsure when the service is
# really ready. Direct invocation works fine in Python 3.12 with
# PYTHONUNBUFFERED=1 and proper log redirection.
Write-Host "[http-server] starting python on :$Port, logging to $OutFile / $ErrFile"
& "$PythonExe" -u -m kotak_bot.http_server --port $Port 1>>"$OutFile" 2>>"$ErrFile"
exit $LASTEXITCODE
