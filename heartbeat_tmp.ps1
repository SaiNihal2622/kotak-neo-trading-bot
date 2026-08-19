$ErrorActionPreference = 'Continue'
Set-Location "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot"

$now = Get-Date
$hour = (Get-Date).Hour
$dow = (Get-Date).DayOfWeek
$isMarketHours = ($dow -ne 'Saturday' -and $dow -ne 'Sunday') -and (($hour -gt 9 -or ($hour -eq 9 -and (Get-Date).Minute -ge 0)) -and ($hour -lt 15 -or ($hour -eq 15 -and (Get-Date).Minute -lt 30)))

# Step 1: alive check with 4h filter
$alive = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*kotak-neo-bot*' -and $_.StartTime -gt (Get-Date).AddHours(-4) } | Measure-Object | Select-Object -ExpandProperty Count
Write-Output "ALIVE_4H: $alive"
Write-Output "MARKET_HOURS: $isMarketHours"

$restarted = $false
$newPid = $null
if ($alive -eq 0 -and $isMarketHours) {
    $alive2 = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*kotak-neo-bot*' } | Measure-Object | Select-Object -ExpandProperty Count
    Write-Output "ALIVE_FULL: $alive2"
    if ($alive2 -eq 0) {
        Write-Output "RESTART_NEEDED: restarting bot"
        Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "-u", "-m", "kotak_bot", "paper" -RedirectStandardOutput "bot_stdout.log" -RedirectStandardError "bot_stderr.log" -WindowStyle Hidden
        $restarted = $true
        Start-Sleep -Seconds 4
        $newPid = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*kotak-neo-bot*' -and $_.StartTime -gt (Get-Date).AddMinutes(-1) } | Select-Object -First 1 -ExpandProperty Id
        Write-Output "RESTARTED_PID: $newPid"
    } else {
        Write-Output "ALIVE_4H_FALSE_ZERO: full count=$alive2, no restart"
    }
} else {
    Write-Output "ALIVE_OK: no restart needed"
}

# Step 2: errors check
if (Test-Path "bot_stderr.log") {
    $errLines = Get-Content "bot_stderr.log" -Tail 200 -ErrorAction SilentlyContinue
    $errs = $errLines | Select-String -Pattern "Traceback|FATAL|Killed|Exception" | Select-Object -Last 3
    if ($errs) {
        Write-Output "RECENT_ERRORS:"
        $errs | ForEach-Object { Write-Output $_.Line }
    } else {
        Write-Output "NO_RECENT_ERRORS"
    }
} else {
    Write-Output "NO_LOG"
}

# Step 3: dashboard health
try {
    $resp = Invoke-WebRequest -Uri "http://localhost:8501/_stcore/health" -UseBasicParsing -TimeoutSec 5
    Write-Output "DASHBOARD: $($resp.StatusCode)"
    if ($resp.StatusCode -ne 200) {
        Write-Output "RESTARTING_DASHBOARD"
        Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "-u", "-m", "streamlit", "run", "dashboard\app.py", "--server.port=8501", "--server.headless=true" -WindowStyle Hidden
    }
} catch {
    Write-Output "DASHBOARD_DOWN: restarting"
    Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "-u", "-m", "streamlit", "run", "dashboard\app.py", "--server.port=8501", "--server.headless=true" -WindowStyle Hidden
}

Write-Output "RESTARTED_FLAG: $restarted"
Write-Output "DONE"
