# =============================================================================
# install_service.ps1 — Register KotakBotPaper + KotakDashboard as NSSM services.
# Idempotent: re-running will re-install with current settings.
# Run as Administrator (required to create Windows services).
# =============================================================================
$ErrorActionPreference = 'Stop'
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  Write-Host "ERROR: Run as Administrator (right-click PowerShell -> Run as administrator)" -ForegroundColor Red
  exit 1
}

$NssmExe  = 'C:\Tools\nssm\nssm-2.24\win64\nssm.exe'
$RepoRoot = 'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot'
$LogDir   = Join-Path $RepoRoot 'Logs'

if (-not (Test-Path $NssmExe)) { throw "NSSM not found at $NssmExe" }
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }

function Install-KotakService {
  param(
    [string]$Name,
    [string]$DisplayName,
    [string]$Description,
    [string]$ScriptPath,
    [string]$StdoutLog,
    [string]$StderrLog
  )
  Write-Host "Installing service: $Name" -ForegroundColor Cyan
  # Remove if already present (idempotent re-install)
  & $NssmExe stop $Name 2>$null
  & $NssmExe remove $Name confirm 2>$null
  & $NssmExe install $Name (Get-Command powershell.exe).Source "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`""
  & $NssmExe set $Name DisplayName $DisplayName | Out-Null
  & $NssmExe set $Name Description $Description | Out-Null
  & $NssmExe set $Name AppDirectory $RepoRoot | Out-Null
  & $NssmExe set $Name Start SERVICE_AUTO_START | Out-Null
  & $NssmExe set $Name AppRestartDelay 5000 | Out-Null
  & $NssmExe set $Name AppStdout "$StdoutLog" | Out-Null
  & $NssmExe set $Name AppStderr "$StderrLog" | Out-Null
  # Rotate NSSM's own log too
  & $NssmExe set $Name AppRotateFiles 1 | Out-Null
  & $NssmExe set $Name AppRotateBytes 52428800 | Out-Null
  # If the process exits within 5s of starting, throttle restart to 5s
  & $NssmExe set $Name AppThrottle 5000 | Out-Null
  # If the process stays alive but misbehaves, NSSM will check via stdout/stderr log age.
  & $NssmExe set $Name AppStopMethodSkip 0 | Out-Null
  # Stop the process cleanly on Windows shutdown
  & $NssmExe set $Name AppStopMethodConsole 1000 | Out-Null
  Write-Host "  Installed: $Name" -ForegroundColor Green
}

Install-KotakService `
  -Name 'KotakBotPaper' `
  -DisplayName 'Kotak Neo Trading Bot (Paper)' `
  -Description 'Indian options/intraday paper-trading bot — NIFTY + BANKNIFTY only, 2-3 lots. Auto-restart on crash.' `
  -ScriptPath (Join-Path $RepoRoot 'system\run_bot.ps1') `
  -StdoutLog (Join-Path $LogDir 'bot_stdout.log') `
  -StderrLog (Join-Path $LogDir 'bot_stderr.log')

Install-KotakService `
  -Name 'KotakDashboard' `
  -DisplayName 'Kotak Trading Bot Dashboard' `
  -Description 'Streamlit dashboard on http://127.0.0.1:8501 — capital, P&L, positions, regime.' `
  -ScriptPath (Join-Path $RepoRoot 'system\run_dashboard.ps1') `
  -StdoutLog (Join-Path $LogDir 'dashboard_stdout.log') `
  -StderrLog (Join-Path $LogDir 'dashboard_stderr.log')

# Write a hint about the actual dashboard entry path
Write-Host ""
Write-Host "Dashboard entry path: dashboard\app.py (not dashboard.py at repo root)" -ForegroundColor Yellow

Write-Host ""
Write-Host "Starting services..." -ForegroundColor Cyan
& $NssmExe start KotakBotPaper
& $NssmExe start KotakDashboard
Write-Host ""
Write-Host "Done. Verify with: Get-Service KotakBotPaper, KotakDashboard" -ForegroundColor Green
