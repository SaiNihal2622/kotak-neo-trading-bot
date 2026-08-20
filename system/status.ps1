# =============================================================================
# status.ps1 — Quick system health check. Run from any shell.
# =============================================================================
$RepoRoot = 'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot'
$LogDir   = Join-Path $RepoRoot 'Logs'

Write-Host "=== KOTAK TRADING BOT SYSTEM STATUS ===" -ForegroundColor Cyan
Write-Host "Time:   $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host ""

# Services
foreach ($svc in 'KotakBotPaper', 'KotakDashboard') {
  $s = Get-Service $svc -ErrorAction SilentlyContinue
  if ($s) {
    $color = if ($s.Status -eq 'Running') { 'Green' } else { 'Red' }
    Write-Host ("Service {0,-18} : {1,-10} (start={2})" -f $svc, $s.Status, $s.StartType) -ForegroundColor $color
  } else {
    Write-Host "Service $svc : NOT INSTALLED" -ForegroundColor Yellow
  }
}
Write-Host ""

# Processes (legacy / NSSM-managed)
$procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'kotak_bot' }
Write-Host "Python processes (kotak_bot): $($procs.Count)"
foreach ($p in $procs) {
  $uptime = [math]::Round(((Get-Date) - $p.CreationDate).TotalMinutes, 1)
  $ws = [math]::Round($p.WorkingSetSize / 1MB, 1)
  Write-Host ("  PID {0,-6} uptime={1,5}m  ws={2}MB" -f $p.ProcessId, $uptime, $ws)
}
Write-Host ""

# Dashboard HTTP
try {
  $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8501/' -UseBasicParsing -TimeoutSec 3
  Write-Host "Dashboard HTTP : $($r.StatusCode)" -ForegroundColor Green
} catch {
  Write-Host "Dashboard HTTP : DOWN ($($_.Exception.Message))" -ForegroundColor Red
}
Write-Host ""

# Last log
$log = Join-Path $LogDir 'bot_stderr.log'
if (Test-Path $log) {
  $age = [math]::Round(((Get-Date) - (Get-Item $log).LastWriteTime).TotalSeconds, 0)
  $size = [math]::Round((Get-Item $log).Length / 1KB, 1)
  Write-Host "bot_stderr.log  : age=${age}s  size=${size}KB"
}
Write-Host ""

# Paper state
$stateFile = Join-Path $RepoRoot 'data_cache\paper_state.json'
if (Test-Path $stateFile) {
  try {
    $s = Get-Content $stateFile -Raw | ConvertFrom-Json
    Write-Host "Cash          : ₹$($s.cash)"
    Write-Host "Realized P&L  : ₹$($s.realized_pnl)"
    Write-Host "Open positions: $($s.positions.Count)"
  } catch {
    Write-Host "paper_state.json unreadable: $($_.Exception.Message)"
  }
}
