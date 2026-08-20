# =============================================================================
# run_bot.ps1 — NSSM service entry point for Kotak Neo Trading Bot (paper mode)
# Invoked by Windows Service Control Manager as the service "KotakBotPaper".
# Restart-on-crash is handled by NSSM (Throttle=5000ms, RestartDelay=0).
# =============================================================================
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'

$RepoRoot = 'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot'
$LogDir   = Join-Path $RepoRoot 'Logs'
$LogFile  = Join-Path $LogDir 'bot_stderr.log'
$OutFile  = Join-Path $LogDir 'bot_stdout.log'
$HeartbeatFile = Join-Path $LogDir 'bot.heartbeat'
$PythonExe = Join-Path $RepoRoot '.venv\Scripts\python.exe'
$EnvFile   = Join-Path $RepoRoot '.env'

# Ensure log directory exists
if (-not (Test-Path $LogDir)) {
  New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

# Rotate log if it exceeds 50MB
if ((Test-Path $LogFile) -and (Get-Item $LogFile).Length -gt 50MB) {
  Move-Item -Path $LogFile -Destination "$LogFile.prev" -Force
}
if ((Test-Path $OutFile) -and (Get-Item $OutFile).Length -gt 50MB) {
  Move-Item -Path $OutFile -Destination "$OutFile.prev" -Force
}

Set-Location $RepoRoot
$env:PYTHONUNBUFFERED = '1'
$env:DOTENV_PATH = $EnvFile
$env:PYTHONPATH = $RepoRoot

# Write a startup marker so healthcheck can detect restarts
$startupInfo = @{
  time = (Get-Date).ToString('o')
  pid  = $PID
  user = $env:USERNAME
  cwd  = (Get-Location).Path
} | ConvertTo-Json -Compress
Set-Content -Path $HeartbeatFile -Value $startupInfo -Encoding UTF8

# Long-lived process. NSSM (or Start-Process) handles stdout/stderr redirect
# via -RedirectStandardOutput / -RedirectStandardError. We must NOT add our own
# `>>` here — that opens a second handle on the same file and causes
# "process cannot access the file" IOExceptions under contention.
& $PythonExe -m kotak_bot paper
exit $LASTEXITCODE
