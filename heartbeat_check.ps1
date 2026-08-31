$ErrorActionPreference = 'Stop'
$now = Get-Date
Write-Host "=== Heartbeat check $($now.ToString('yyyy-MM-dd HH:mm:ss')) IST ==="

# Step 1: Check if bot is alive (path filter + 4h window)
$alive = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*kotak-neo-bot*' -and $_.StartTime -gt (Get-Date).AddHours(-4) } | Measure-Object | Select-Object -ExpandProperty Count
$aliveAll = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*kotak-neo-bot*' } | Measure-Object | Select-Object -ExpandProperty Count
Write-Host "alive4h=$alive aliveAll=$aliveAll"

# Market hours check (9:00-15:30 IST Mon-Fri)
$isMarketHours = ($now.DayOfWeek -ge 'Monday' -and $now.DayOfWeek -le 'Friday') -and (($now.Hour -gt 9) -or ($now.Hour -eq 9 -and $now.Minute -ge 0)) -and (($now.Hour -lt 15) -or ($now.Hour -eq 15 -and $now.Minute -le 30))
Write-Host "isMarketHours=$isMarketHours"

# Get main bot PID (oldest)
$mainProc = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*kotak-neo-bot*' } | Sort-Object StartTime | Select-Object -First 1
$mainPid = 0
$mainAgeMin = 0
if ($mainProc) {
    $mainPid = $mainProc.Id
    $mainAgeMin = [math]::Round(((Get-Date) - $mainProc.StartTime).TotalMinutes, 1)
}
Write-Host "mainPid=$mainPid mainAgeMin=$mainAgeMin"

# Step 2: Check stderr log for errors
$logPath = "bot_stderr.log"
$logSize = 0
$logAgeMin = -1
$errs = @()
if (Test-Path $logPath) {
    $logItem = Get-Item $logPath
    $logSize = $logItem.Length
    $logAgeMin = [math]::Round(((Get-Date) - $logItem.LastWriteTime).TotalMinutes, 1)
    Write-Host "logSize=$logSize logAgeMin=$logAgeMin"
    $errs = @(Select-String -Path $logPath -Pattern 'Traceback|FATAL|Killed|Exception' -ErrorAction SilentlyContinue | Select-Object -Last 3)
    if ($errs.Count -gt 0) {
        Write-Host "ERRORS FOUND:"
        foreach ($e in $errs) {
            Write-Host "  L$($e.LineNumber): $($e.Line)"
        }
    } else {
        Write-Host "log clean (0 error patterns)"
    }
} else {
    Write-Host "no log file"
}

# Step 3: Check dashboard
$dashOk = $false
try {
    $resp = Invoke-WebRequest -Uri 'http://localhost:8501/_stcore/health' -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
    $dashOk = ($resp.StatusCode -eq 200)
    Write-Host "dash=200 OK"
} catch {
    Write-Host "dash DOWN: $($_.Exception.Message)"
}

# Step 3b: Restart dashboard if down
if (-not $dashOk) {
    Write-Host "RESTART DASHBOARD: starting streamlit..."
    Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList @("-u", "-m", "streamlit", "run", "dashboard\app.py", "--server.port=8501", "--server.headless=true") -WindowStyle Hidden
    Start-Sleep -Seconds 3
}

# Step 4: If aliveAll=0 AND isMarketHours, restart bot
$restarted = $false
$restartPid = 0
if ($aliveAll -eq 0 -and $isMarketHours) {
    Write-Host "RESTART: bot not running during market hours, restarting..."
    $proc = Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList @("-u", "-m", "kotak_bot", "paper") -RedirectStandardOutput "bot_stdout.log" -RedirectStandardError "bot_stderr.log" -WindowStyle Hidden -PassThru
    $restartPid = $proc.Id
    $restarted = $true
    Start-Sleep -Seconds 3
} else {
    Write-Host "no restart needed"
}

# Update state file
$stateDir = "data_cache"
if (-not (Test-Path $stateDir)) {
    New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
}
$action = if ($restarted) { "restarted" } else { "silent" }
$state = @{
    err        = 0
    tc         = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ss")
    alive4     = $alive
    aliveAll   = $aliveAll
    dash       = if ($dashOk) { 200 } else { 0 }
    mktHours   = $isMarketHours
    action     = $action
    botPid     = $mainPid
    botAgeMin  = $mainAgeMin
    logSize    = $logSize
    logAgeMin  = $logAgeMin
    restartReason = if ($restarted) { "aliveAll=0 during market hours" } else { "" }
}
$state | ConvertTo-Json | Set-Content -Path "$stateDir/heartbeat_state.json" -Encoding UTF8
Write-Host "state saved to $stateDir/heartbeat_state.json"
Write-Host "FINAL: action=$action restartPid=$restartPid errors=$($errs.Count)"

# Step 5: Telegram notification only on action
if ($restarted) {
    $msg = "Bot was down, restarted. PID: $restartPid"
    Write-Host "TELEGRAM: $msg"
    # Note: actual Telegram send is handled by separate mechanism (per spec the cron prompt mentions Telegram)
}

if ($errs.Count -gt 0) {
    Write-Host "TELEGRAM CRITICAL: $($errs.Count) new error pattern(s) in log"
}
