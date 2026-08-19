$ErrorActionPreference = 'Stop'
$nowIst = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
$nowIst += ' IST'
Write-Host "=== OFF-MARKET HEARTBEAT at $nowIst ==="
Write-Host ""

# Check 1: Bot processes
Write-Host "--- CHECK 1: BOT PROCESSES ---"
try {
  $bots = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'kotak_bot' } |
    Select-Object ProcessId, ParentProcessId,
      @{N='uptime_min';E={[math]::Round(((Get-Date) - $_.CreationDate).TotalMinutes,1)}},
      @{N='ws_mb';E={[math]::Round($_.WorkingSetSize/1MB,1)}}
  if ($bots) {
    Write-Host "BOT_PROCS_COUNT=$($bots.Count)"
    foreach ($b in $bots) {
      Write-Host "  PID=$($b.ProcessId) parent=$($b.ParentProcessId) up=$($b.uptime_min)m ws=$($b.ws_mb)MB"
    }
  } else {
    Write-Host "BOT_PROCS_COUNT=0 (DEAD)"
  }
} catch {
  Write-Host "CHECK 1 ERROR: $($_.Exception.Message)"
}
Write-Host ""

# Check 2 & 3: Log tail 5 and 20
Write-Host "--- CHECK 2/3: LOG TAILS ---"
$logRoot = 'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\bot_stderr.log'
try {
  if (Test-Path $logRoot) {
    $logItem = Get-Item $logRoot
    $ageMin = [math]::Round(((Get-Date) - $logItem.LastWriteTime).TotalMinutes, 2)
    Write-Host "ACTIVE_LOG: $logRoot (size=$($logItem.Length) bytes, age=$ageMin min)"
    Write-Host "--- Last 5 lines ---"
    Get-Content $logRoot -Tail 5 | ForEach-Object { Write-Host "  $_" }
    Write-Host "--- Last 20 lines (key patterns only) ---"
    Get-Content $logRoot -Tail 30 | Where-Object { $_ -match 'NEW_ORDER|FILLED|EXIT|REGIME|ERROR|Traceback|REJECTED|smart-exit|EOD|skip:|backup|compliance' } | Select-Object -Last 15 | ForEach-Object { Write-Host "  $_" }
  } else {
    Write-Host "ACTIVE LOG MISSING"
  }
} catch {
  Write-Host "CHECK 2/3 ERROR: $($_.Exception.Message)"
}
Write-Host ""

# Check 4: Capital + P&L
Write-Host "--- CHECK 4: CAPITAL + P&L ---"
$pyPath = 'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\scripts\tmp_capital_check.py'
Set-Content -Path $pyPath -NoNewline -Encoding UTF8 -Value @"
import json
p = r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\paper_state.json'
try:
    with open(p, 'r', encoding='utf-8') as f:
        s = json.load(f)
    cash = s.get('cash')
    realized = s.get('realized_pnl')
    orders = s.get('orders', {})
    positions = s.get('positions', [])
    if isinstance(positions, dict):
        positions = list(positions.values())
    npos = len([pp for pp in positions if isinstance(pp, dict) and pp.get('qty', 0) != 0])
    print(f"cash={cash} realized={realized} orders={len(orders)} open_positions={npos}")
except Exception as e:
    print(f"ERROR: {e}")
"@
try {
  $venv = 'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\.venv\Scripts\python.exe'
  & $venv $pyPath
} catch {
  Write-Host "CHECK 4 ERROR: $($_.Exception.Message)"
}
Write-Host ""

# Check 6: Dashboard port
Write-Host "--- CHECK 6: DASHBOARD :8501 ---"
try {
  $d = Test-NetConnection 127.0.0.1 -Port 8501 -InformationLevel Quiet -WarningAction SilentlyContinue
  Write-Host "DASH_8501=$d"
} catch {
  Write-Host "DASH_8501=ERROR: $($_.Exception.Message)"
}
Write-Host ""

# Check 7: 15:45 backup cron - look for backup-related log activity
Write-Host "--- CHECK 7: 15:45 EOD BACKUP CHECK ---"
$backupDir = 'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\backups'
if (Test-Path $backupDir) {
  Get-ChildItem $backupDir -File | Sort-Object LastWriteTime -Descending | Select-Object -First 3 | ForEach-Object {
    Write-Host "  backup: $($_.Name) size=$($_.Length) mtime=$($_.LastWriteTime.ToString('HH:mm:ss'))"
  }
} else {
  Write-Host "  no backup dir at $backupDir"
}

Write-Host ""
Write-Host "=== END OFF-MARKET HEARTBEAT ==="
