# UAC-elevated: stop services, reset state, restart
$ErrorActionPreference = 'Stop'
$nssm = 'C:\Tools\nssm\nssm-2.24\win64\nssm.exe'
$RepoRoot = 'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot'
$DataCache = Join-Path $RepoRoot 'data_cache'

# 1) Stop services
Write-Host "Stopping services..."
& $nssm stop KotakBotPaper 2>&1 | Out-Null
& $nssm stop KotakDashboard 2>&1 | Out-Null
Start-Sleep -Seconds 5
# Force-kill any lingering procs
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object {
  $_.CommandLine -match 'kotak_bot' -or $_.CommandLine -match 'streamlit'
} | ForEach-Object {
  Write-Host "  Killing PID $($_.ProcessId)"
  Stop-Process -Id $_.ProcessId -Force
}
Start-Sleep -Seconds 3
# Verify
$alive = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'kotak_bot|streamlit' }
Write-Host "  Lingering procs: $($alive.Count)"

# 2) Backup current state
$backupDir = Join-Path $DataCache 'reset_backup_2026-08-21_pre-market'
if (-not (Test-Path $backupDir)) { New-Item -ItemType Directory -Path $backupDir -Force | Out-Null }
$ts = Get-Date -Format 'yyyyMMdd_HHmmss'
foreach ($f in 'paper_state.json', 'trades_state.json', 'order_manager_state.json') {
  $src = Join-Path $DataCache $f
  if (Test-Path $src) {
    Copy-Item $src "$backupDir\$($f.Replace('.json','')).bak_$ts" -Force
    Write-Host "  Backed up $f"
  }
}

# 3) Reset state files
$cleanPaper = '{"cash":100000.0,"realized_pnl":0.0,"positions":{},"orders":{}}'
$cleanTrades = '{"trades":{},"symbol_to_trade":{}}'
$cleanOrderMgr = '{"trades":{}}'
Set-Content -Path "$DataCache\paper_state.json" -Value $cleanPaper -Encoding UTF8 -NoNewline
Set-Content -Path "$DataCache\trades_state.json" -Value $cleanTrades -Encoding UTF8 -NoNewline
Set-Content -Path "$DataCache\order_manager_state.json" -Value $cleanOrderMgr -Encoding UTF8 -NoNewline
Write-Host ""
Write-Host "RESET DONE:"
Write-Host "  paper_state.json: cash=100000, realized=0, positions=0, orders=0"
Write-Host "  trades_state.json: empty"
Write-Host "  order_manager_state.json: empty"

# 4) Start services
Write-Host ""
Write-Host "Starting services..."
& $nssm start KotakBotPaper
& $nssm start KotakDashboard
Start-Sleep -Seconds 8
Write-Host ""
Write-Host "=== Final state ==="
& $nssm status KotakBotPaper
& $nssm status KotakDashboard
Write-Host ""
# Verify state files weren't overwritten yet
$paperContent = Get-Content "$DataCache\paper_state.json" -Raw
if ($paperContent -match '"cash":\s*100000') {
  Write-Host "paper_state.json: STILL CLEAN (cash=100000) — NSSM bot has not yet persisted" -ForegroundColor Green
} else {
  Write-Host "paper_state.json: ALREADY OVERWRITTEN by bot" -ForegroundColor Red
  Write-Host "  $paperContent"
}
