$ErrorActionPreference = 'Stop'
$nowIst = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
$nowIst += ' IST'
Write-Host "=== ACTIVE MONITOR TICK at $nowIst ==="
Write-Host ""

# Check 1: Bot processes
Write-Host "--- CHECK 1: BOT PROCESSES ---"
try {
  $bots = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'kotak_bot' } |
    Select-Object ProcessId, ParentProcessId,
      @{N='uptime_min';E={[math]::Round(((Get-Date) - $_.CreationDate).TotalMinutes,1)}},
      @{N='ws_mb';E={[math]::Round($_.WorkingSetSize/1MB,1)}},
      @{N='cmd';E={$_.CommandLine.Substring(0,[Math]::Min(120,$_.CommandLine.Length))}}
  if ($bots) {
    Write-Host "BOT_PROCS_COUNT=$($bots.Count)"
    foreach ($b in $bots) {
      Write-Host "  PID=$($b.ProcessId) parent=$($b.ParentProcessId) up=$($b.uptime_min)m ws=$($b.ws_mb)MB"
      Write-Host "    cmd: $($b.cmd)"
    }
  } else {
    Write-Host "BOT_PROCS_COUNT=0 (DEAD)"
  }
} catch {
  Write-Host "CHECK 1 ERROR: $($_.Exception.Message)"
}
Write-Host ""

# Check 2 & 3: Log tail 5 and 20
Write-Host "--- CHECK 2/3: LOG TAILS (active log at CWD root) ---"
$logRoot = 'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\bot_stderr.log'
$logStale = 'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\Logs\bot_stderr.log'
try {
  if (Test-Path $logRoot) {
    $logItem = Get-Item $logRoot
    $ageMin = [math]::Round(((Get-Date) - $logItem.LastWriteTime).TotalMinutes, 2)
    Write-Host "ACTIVE_LOG: $logRoot (size=$($logItem.Length) bytes, age=$ageMin min)"
    Write-Host "--- Last 5 lines ---"
    Get-Content $logRoot -Tail 5 | ForEach-Object { Write-Host "  $_" }
    Write-Host "--- Last 20 lines (key patterns only) ---"
    Get-Content $logRoot -Tail 20 | Where-Object { $_ -match 'NEW_ORDER|FILLED|EXIT|REGIME|ERROR|Traceback|REJECTED|smart-exit|EOD|skip:' } | ForEach-Object { Write-Host "  $_" }
  } else {
    Write-Host "ACTIVE LOG MISSING: $logRoot"
  }
  if (Test-Path $logStale) {
    $staleItem = Get-Item $logStale
    Write-Host "STALE_LOG: $logStale (size=$($staleItem.Length) bytes)"
  } else {
    Write-Host "STALE_LOG: not present"
  }
} catch {
  Write-Host "CHECK 2/3 ERROR: $($_.Exception.Message)"
}
Write-Host ""

# Check 4: Capital + P&L via temp .py (avoid long inline JSON)
Write-Host "--- CHECK 4: CAPITAL + P&L ---"
$pyPath = 'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\scripts\tmp_capital_check.py'
Set-Content -Path $pyPath -NoNewline -Encoding UTF8 -Value @"
import json, sys
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
    npos = len([p for p in positions if isinstance(p, dict) and p.get('qty', 0) != 0])
    print(f"cash={cash} realized={realized} orders={len(orders)} open_positions={npos}")
    if positions:
        for pp in positions[:3]:
            if isinstance(pp, dict):
                print(f"  pos sample: {pp.get('symbol', pp.get('scrip', '?'))} qty={pp.get('qty', '?')} pnl={pp.get('pnl', '?')}")
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

# Check 5: Today's open positions (trades_state.json - DICT not list!)
Write-Host "--- CHECK 5: TODAY'S OPEN POSITIONS ---"
$pyTrades = 'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\scripts\tmp_trades_check.py'
Set-Content -Path $pyTrades -NoNewline -Encoding UTF8 -Value @"
import json
p = r'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\trades_state.json'
try:
    with open(p, 'r', encoding='utf-8') as f:
        t = json.load(f)
    if isinstance(t, dict):
        positions = t.get('positions', {})
        orders = t.get('orders', {})
        trades = t.get('trades', {})
        npos_open = 0
        if isinstance(positions, dict):
            for v in positions.values():
                if isinstance(v, dict) and v.get('status', 'open') == 'open':
                    npos_open += 1
        elif isinstance(positions, list):
            npos_open = sum(1 for x in positions if isinstance(x, dict) and x.get('status') == 'open')
        norders_open = 0
        if isinstance(orders, dict):
            for v in orders.values():
                if isinstance(v, dict) and v.get('status', 'open') == 'open':
                    norders_open += 1
        elif isinstance(orders, list):
            norders_open = sum(1 for x in orders if isinstance(x, dict) and x.get('status') == 'open')
        print(f"trades_state: positions_total={len(positions)} open={npos_open} orders_total={len(orders)} open={norders_open} trades_total={len(trades)}")
    else:
        print(f"trades_state is {type(t).__name__} (not dict)")
except Exception as e:
    print(f"ERROR: {e}")
"@
try {
  & $venv $pyTrades
} catch {
  Write-Host "CHECK 5 ERROR: $($_.Exception.Message)"
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

Write-Host "=== END ACTIVE MONITOR ==="
