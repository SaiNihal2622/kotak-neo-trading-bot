# Fallback: start bot + dashboard manually (no NSSM). Used when NSSM service
# is unavailable (admin elevation pending or service is in Paused state).
$ErrorActionPreference = 'Continue'
$RepoRoot = 'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot'
$LogDir   = Join-Path $RepoRoot 'Logs'
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }

$env:DOTENV_PATH  = Join-Path $RepoRoot '.env'
$env:PYTHONUNBUFFERED = '1'
$env:PYTHONPATH    = $RepoRoot
$ps = (Get-Command powershell.exe).Source

# Kill any old procs
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object {
  $_.CommandLine -match 'kotak_bot' -or $_.CommandLine -match 'streamlit'
} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 2

# Start bot
$botArgs = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $RepoRoot 'system/run_bot.ps1'))
$bot = Start-Process -FilePath $ps -ArgumentList $botArgs -WorkingDirectory $RepoRoot `
  -RedirectStandardOutput (Join-Path $LogDir 'bot_stdout.log') `
  -RedirectStandardError  (Join-Path $LogDir 'bot_stderr.log') `
  -WindowStyle Hidden -PassThru

# Start dashboard
$dashArgs = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $RepoRoot 'system/run_dashboard.ps1'))
$dash = Start-Process -FilePath $ps -ArgumentList $dashArgs -WorkingDirectory $RepoRoot `
  -RedirectStandardOutput (Join-Path $LogDir 'dashboard_stdout.log') `
  -RedirectStandardError  (Join-Path $LogDir 'dashboard_stderr.log') `
  -WindowStyle Hidden -PassThru

Write-Host "Bot wrapper PID: $($bot.Id)"
Write-Host "Dashboard wrapper PID: $($dash.Id)"
Start-Sleep -Seconds 8

# Verify
$procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'kotak_bot' }
Write-Host ""
Write-Host "=== kotak_bot procs after 8s ==="
foreach ($p in $procs) {
  $u = [math]::Round(((Get-Date) - $p.CreationDate).TotalMinutes, 1)
  Write-Host "  PID $($p.ProcessId) uptime=$u m"
}
try {
  $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8501/' -UseBasicParsing -TimeoutSec 5
  Write-Host "Dashboard HTTP: $($r.StatusCode)"
} catch {
  Write-Host "Dashboard: DOWN"
}
