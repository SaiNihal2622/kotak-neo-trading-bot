$ErrorActionPreference = 'Stop'
$now = Get-Date
$projectRoot = 'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot'
$logPath = Join-Path $projectRoot 'logs\bot_stderr.log'
$paperPath = Join-Path $projectRoot 'data_cache\paper_state.json'
$tradesPath = Join-Path $projectRoot 'data_cache\trades_state.json'

Write-Host "=== BOT PROCESSES ==="
$botProcs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'kotak_bot' } |
    Select-Object ProcessId, ParentProcessId, CreationDate, @{N='uptime_min';E={[math]::Round(((Get-Date) - $_.CreationDate).TotalMinutes,1)}}, @{N='ws_mb';E={[math]::Round($_.WorkingSetSize/1MB,1)}}, CommandLine
foreach ($p in $botProcs) {
    Write-Host ("PID={0} PARENT={1} UP={2}min WS={3}MB" -f $p.ProcessId, $p.ParentProcessId, $p.uptime_min, $p.ws_mb)
}

Write-Host ""
Write-Host "=== LOG TAIL 5 ==="
if (Test-Path $logPath) {
    Get-Content $logPath -Tail 5 | ForEach-Object { Write-Host $_ }
} else {
    Write-Host "LOG_PATH_MISSING: $logPath"
}

Write-Host ""
Write-Host "=== LOG TAIL 20 PATTERNS ==="
if (Test-Path $logPath) {
    $tail20 = Get-Content $logPath -Tail 20
    $lastLine = ($tail20 | Select-Object -Last 1)
    $hasOrder = ($tail20 | Select-String -Pattern '(PLACE|ORDER|FILLED|FILL).*PAPER' -SimpleMatch).Count -gt 0
    $hasFill = ($tail20 | Select-String -Pattern 'FILLED' -SimpleMatch).Count -gt 0
    $hasExit = ($tail20 | Select-String -Pattern '(EXIT|smart-exit|SL_HIT|TARGET_HIT)' -SimpleMatch).Count -gt 0
    $hasRegime = ($tail20 | Select-String -Pattern 'regime' -SimpleMatch).Count -gt 0
    $hasError = ($tail20 | Select-String -Pattern 'Traceback|FATAL|Killed|REJECTED' -SimpleMatch).Count -gt 0
    $lastLogWrite = (Get-Item $logPath).LastWriteTime
    $logAge = [math]::Round(($now - $lastLogWrite).TotalMinutes, 1)
    Write-Host "LAST_LINE: $lastLine"
    Write-Host "LAST_WRITE: $lastLogWrite (age=${logAge}m)"
    Write-Host "NEW_ORDER=$hasOrder FILL=$hasFill EXIT=$hasExit REGIME=$hasRegime ERROR=$hasError"
}

Write-Host ""
Write-Host "=== DASHBOARD ==="
$dashOk = (Test-NetConnection 127.0.0.1 -Port 8501 -InformationLevel Quiet) -eq 'True'
Write-Host "DASH_OK=$dashOk"

Write-Host ""
Write-Host "=== PAPER STATE ==="
$venvPy = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (Test-Path $paperPath) {
    & $venvPy -c "import json; s=json.load(open(r'$paperPath')); print('CASH=', s.get('cash')); print('REALIZED=', s.get('realized_pnl')); print('ORDERS=', len(s.get('orders',{}))); print('POSITIONS=', len(s.get('positions',{})))"
} else {
    Write-Host "PAPER_STATE_MISSING"
}

Write-Host ""
Write-Host "=== TRADES STATE ==="
if (Test-Path $tradesPath) {
    & $venvPy -c "import json; t=json.load(open(r'$tradesPath')); open_trades=[x for x in t if x.get('status')=='open']; print('OPEN_TRADES=', len(open_trades))"
} else {
    Write-Host "TRADES_STATE_MISSING"
}
