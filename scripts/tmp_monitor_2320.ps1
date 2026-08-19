$ErrorActionPreference = 'Stop'
$projectRoot = 'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot'
$activeLog = Join-Path $projectRoot 'bot_stderr.log'
$staleLog = Join-Path $projectRoot 'Logs\bot_stderr.log'
$nowIst = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
$logMtime = (Get-Item $activeLog -ErrorAction SilentlyContinue).LastWriteTime
$logAgeMin = if ($logMtime) { [math]::Round(((Get-Date) - $logMtime).TotalMinutes, 2) } else { -1 }
$staleMtime = (Get-Item $staleLog -ErrorAction SilentlyContinue).LastWriteTime

# 1. Bot procs
$procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'kotak_bot' } |
    Select-Object ProcessId, ParentProcessId, CreationDate, @{N='uptime_min';E={[math]::Round(((Get-Date) - $_.CreationDate).TotalMinutes,1)}}, @{N='ws_mb';E={[math]::Round($_.WorkingSetSize/1MB,1)}}, @{N='cmd';E={$_.CommandLine.Substring(0, [Math]::Min(80, $_.CommandLine.Length))}}
$procCount = $procs.Count
$pidList = ($procs | ForEach-Object { $_.ProcessId }) -join ','

# 2. Last 5 log lines (active root log)
$tail5 = Get-Content $activeLog -Tail 5 -ErrorAction SilentlyContinue

# 3. Last 20 lines pattern scan
$tail20 = Get-Content $activeLog -Tail 20 -ErrorAction SilentlyContinue
$newOrders = ($tail20 | Select-String -Pattern 'NEW_ORDER|order_placed|placing order' -SimpleMatch).Count
$fills = ($tail20 | Select-String -Pattern 'FILLED|FILL|filled' -SimpleMatch).Count
$exits = ($tail20 | Select-String -Pattern 'EXIT|exit|smart-exit' -SimpleMatch).Count
$errors = ($tail20 | Select-String -Pattern 'ERROR|Traceback' -SimpleMatch).Count
$regime = ($tail20 | Select-String -Pattern 'regime|REGIME' -SimpleMatch).Count

# 4. Capital
$paperState = Get-Content (Join-Path $projectRoot 'data_cache\paper_state.json') -Raw -ErrorAction SilentlyContinue
$capitalInfo = ''
if ($paperState) {
    try {
        $ps = $paperState | ConvertFrom-Json -ErrorAction Stop
        $capitalInfo = "cash=$($ps.cash) realized=$($ps.realized_pnl) orders=$($ps.orders.Count) positions=$($ps.positions.Count)"
    } catch {
        $capitalInfo = "ERR_PARSE: $($_.Exception.Message)"
    }
}

# 5. Open positions
$positionsInfo = ''
$tradesState = Get-Content (Join-Path $projectRoot 'data_cache\trades_state.json') -Raw -ErrorAction SilentlyContinue
if ($tradesState) {
    try {
        $ts = $tradesState | ConvertFrom-Json -ErrorAction Stop
        $openCount = 0
        $openSummary = @()
        if ($ts.positions) {
            foreach ($p in $ts.positions.PSObject.Properties) {
                $pos = $p.Value
                if ($pos.status -eq 'open' -or $pos.status -eq 'OPEN') {
                    $openCount++
                    $openSummary += "$($pos.symbol):qty=$($pos.qty):pnl=$($pos.pnl)"
                }
            }
        }
        $positionsInfo = "open_positions=$openCount $('['+($openSummary -join ' | ')+']')"
    } catch {
        $positionsInfo = "ERR_TRADES: $($_.Exception.Message)"
    }
}

# 6. Dashboard
$dash = Test-NetConnection 127.0.0.1 -Port 8501 -InformationLevel Quiet -WarningAction SilentlyContinue

# Backups check
$backupDir = Join-Path $projectRoot 'data_cache\backups'
$backupCount = (Get-ChildItem $backupDir -ErrorAction SilentlyContinue | Where-Object { $_.LastWriteTime -gt (Get-Date).AddHours(-6) }).Count

# Build report
Write-Output "=== 23:20 IST 6-CHECK ==="
Write-Output "NOW_IST=$nowIst"
Write-Output "BOT_PROCS=$procCount PIDs=$pidList"
Write-Output "ACTIVE_LOG_AGE_MIN=$logAgeMin (stale_mtime=$staleMtime)"
Write-Output "DASH_8501=$dash"
Write-Output "TAIL5:"
$tail5 | ForEach-Object { Write-Output "  $_" }
Write-Output "PATTERNS_20: NEW_ORDER=$newOrders FILL=$fills EXIT=$exits ERROR=$errors REGIME=$regime"
Write-Output "CAPITAL: $capitalInfo"
Write-Output "POSITIONS: $positionsInfo"
Write-Output "BACKUPS_LAST6H=$backupCount"
Write-Output "==========================="
