$ErrorActionPreference = 'Stop'
$ErrorActionPreference = 'Continue'
$projectDir = 'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot'
Set-Location $projectDir

Write-Host '=== 09:00 IST — MARKET JUST OPENED ==='
Write-Host "Current IST: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"

# 1. Bot processes (WMI strict - kotak_bot in CommandLine)
Write-Host ''
Write-Host '=== 1. BOT PROCS (WMI kotak_bot match) ==='
$botProcs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'kotak_bot' }
if ($botProcs) {
    $botProcs | Select-Object ProcessId, CreationDate, @{N='uptime_min';E={[math]::Round(((Get-Date) - $_.CreationDate).TotalMinutes,1)}}, @{N='ws_mb';E={[math]::Round($_.WorkingSetSize/1MB,1)}}, @{N='cmdline';E={$_.CommandLine.Substring(0,[math]::Min(80,$_.CommandLine.Length))}} | Format-Table -AutoSize | Out-String | Write-Host
} else {
    Write-Host 'NO BOT PROCS FOUND'
}

# 2. Active log path resolution (cwd-relative vs Logs\)
Write-Host '=== 2. LOG FILES ==='
$cwdLog = Get-Item 'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\bot_stderr.log' -ErrorAction SilentlyContinue
$logsDirLog = Get-Item 'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\Logs\bot_stderr.log' -ErrorAction SilentlyContinue
if ($cwdLog) {
    $ageMin = [math]::Round(((Get-Date) - $cwdLog.LastWriteTime).TotalMinutes, 2)
    Write-Host "cwd bot_stderr.log: size=$($cwdLog.Length)B lastWrite=$($cwdLog.LastWriteTime.ToString('HH:mm:ss')) age_min=$ageMin"
} else { Write-Host 'cwd bot_stderr.log: NOT FOUND' }
if ($logsDirLog) {
    $ageMin = [math]::Round(((Get-Date) - $logsDirLog.LastWriteTime).TotalMinutes, 2)
    Write-Host "Logs\bot_stderr.log: size=$($logsDirLog.Length)B lastWrite=$($logsDirLog.LastWriteTime.ToString('HH:mm:ss')) age_min=$ageMin"
} else { Write-Host 'Logs\bot_stderr.log: NOT FOUND' }
# FIX 2026-08-25: pick the NEWEST of the two — bot actually writes to Logs\bot_stderr.log
# but the cwd-relative copy has been FROZEN at 2026-08-20 02:27 (5 days stale).
# Use whichever was modified more recently.
if ($logsDirLog -and $cwdLog) {
    $activeLog = if ($logsDirLog.LastWriteTime -gt $cwdLog.LastWriteTime) { $logsDirLog } else { $cwdLog }
} elseif ($logsDirLog) {
    $activeLog = $logsDirLog
} else {
    $activeLog = $cwdLog
}
$activePath = if ($activeLog) { $activeLog.FullName } else { $null }

# 3. Last 5 log lines (active = whichever was most recently written)
Write-Host ''
Write-Host '=== 3. LAST 5 LOG LINES (active log) ==='
if ($activePath) {
    Get-Content $activePath -Tail 5 | ForEach-Object { Write-Host $_ }
} else {
    Write-Host 'no log to read'
}

# 4. Error scan (Traceback/FATAL/Killed/Exception)
Write-Host ''
Write-Host '=== 4. ERROR SCAN (last 5) ==='
if ($activePath) {
    $errs = Select-String -Path $activePath -Pattern 'Traceback|FATAL|Killed|Exception' -ErrorAction SilentlyContinue | Select-Object -Last 5
    if ($errs) {
        foreach ($e in $errs) {
            Write-Host ("L{0}: {1}" -f $e.LineNumber, $e.Line.Substring(0, [math]::Min(160, $e.Line.Length)))
        }
    } else {
        Write-Host 'NO_ERRORS'
    }
}

# 5. Scan cycle / regime / fill activity (last 20 lines)
Write-Host ''
Write-Host '=== 5. ACTIVITY SIGNALS (last 20 lines, grep) ==='
if ($activePath) {
    $sigs = Select-String -Path $activePath -Pattern 'cycle=|FILLED|REJECTED|smart-exit|EOD|regime|FILL|order|position|tick_count' -ErrorAction SilentlyContinue | Select-Object -Last 10
    if ($sigs) {
        foreach ($s in $sigs) {
            Write-Host ("L{0}: {1}" -f $s.LineNumber, $s.Line.Substring(0, [math]::Min(140, $s.Line.Length)))
        }
    } else {
        Write-Host 'no matching signals'
    }
}

# 6. Paper state
Write-Host ''
Write-Host '=== 6. PAPER STATE ==='
$ps = Get-Content 'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\paper_state.json' -Raw -ErrorAction SilentlyContinue
if ($ps) {
    $j = $ps | ConvertFrom-Json
    $psAgeMin = [math]::Round(((Get-Date) - (Get-Item 'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\paper_state.json').LastWriteTime).TotalMinutes, 1)
    Write-Host "cash=$($j.cash) realized_pnl=$($j.realized_pnl) orders=$($j.orders.Count) state_age_min=$psAgeMin"
    $openTrades = $j.positions | Where-Object { $_.qty -ne 0 } | Measure-Object | Select-Object -ExpandProperty Count
    Write-Host "open_positions_count=$openTrades"
} else { Write-Host 'paper_state.json missing' }

# 7. Dashboard
Write-Host ''
Write-Host '=== 7. DASHBOARD ==='
$tnc = Test-NetConnection 127.0.0.1 -Port 8501 -InformationLevel Quiet
Write-Host "port 8501 TNC = $tnc"
$owner = Get-NetTCPConnection -LocalPort 8501 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty OwningProcess
if ($owner) {
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$owner" -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Host "port 8501 owner: PID=$($proc.ProcessId) path=$($proc.Name) started=$($proc.CreationDate.ToString('HH:mm:ss'))"
    }
}
