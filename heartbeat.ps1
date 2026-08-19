$ErrorActionPreference = 'Stop'
$py = ".\.venv\Scripts\python.exe"

# Step 1: First check (4h window) — only counts processes started in last 4 hours
$alive = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*kotak-neo-bot*' -and $_.StartTime -gt (Get-Date).AddHours(-4) } | Measure-Object | Select-Object -ExpandProperty Count
Write-Output "FIRST_CHECK_4H: $alive"

# Compute IST market hours (9:00-15:30 Mon-Fri, no DST in IST).
# System is in IST (UTC+05:30), so Get-Date returns local IST directly — no +5:30 conversion.
$now = Get-Date
$hour = $now.Hour
$minute = $now.Minute
$dayOfWeek = $now.DayOfWeek
$isMarketHours = ($dayOfWeek -ne 'Saturday' -and $dayOfWeek -ne 'Sunday') -and (
    ($hour -gt 9 -or ($hour -eq 9 -and $minute -ge 0)) -and
    ($hour -lt 15 -or ($hour -eq 15 -and $minute -le 30))
)
Write-Output ("LOCAL_TIME: {0} | Day: {1} | MarketHours: {2}" -f $now.ToString('yyyy-MM-dd HH:mm:ss'), $dayOfWeek, $isMarketHours)

$needsSecondCheck = ($alive -eq 0) -and $isMarketHours
$restarted = $false
$restartPid = $null

if ($needsSecondCheck) {
    $fullCount = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*kotak-neo-bot*' } | Measure-Object | Select-Object -ExpandProperty Count
    Write-Output "SECOND_CHECK_FULL: $fullCount"
    if ($fullCount -eq 0) {
        Write-Output "RESTARTING_BOT"
        $proc = Start-Process -FilePath $py -ArgumentList "-u", "-m", "kotak_bot", "paper" -RedirectStandardOutput "bot_stdout.log" -RedirectStandardError "bot_stderr.log" -WindowStyle Hidden -PassThru
        $restarted = $true
        $restartPid = $proc.Id
        Write-Output "RESTARTED_PID: $restartPid"
    } else {
        Write-Output "BOT_ALIVE_VIA_SECOND_CHECK: $fullCount"
    }
} else {
    Write-Output "NO_RESTART_NEEDED"
}

# Step 2: Check bot stderr log for errors
$logPath = "Logs\bot_stderr.log"
if (Test-Path $logPath) {
    $errors = Select-String -Path $logPath -Pattern 'Traceback|FATAL|Killed|Exception' | Select-Object -Last 3
    Write-Output "---LAST_3_ERRORS---"
    if ($errors) {
        $errors | ForEach-Object { Write-Output $_.Line }
    } else {
        Write-Output "NO_ERRORS"
    }
} else {
    Write-Output "LOG_NOT_FOUND: $logPath"
}

# Step 3: Check dashboard health
$dashboardRestarted = $false
try {
    $dashResp = Invoke-WebRequest -Uri "http://localhost:8501/_stcore/health" -UseBasicParsing -TimeoutSec 5
    Write-Output ("DASHBOARD: {0} ({1})" -f $dashResp.StatusCode, $dashResp.StatusDescription)
} catch {
    Write-Output ("DASHBOARD_DOWN: {0}" -f $_.Exception.Message)
    Write-Output "RESTARTING_DASHBOARD"
    $dashProc = Start-Process -FilePath $py -ArgumentList "-u", "-m", "streamlit", "run", "dashboard\app.py", "--server.port=8501", "--server.headless=true" -WindowStyle Hidden -PassThru
    $dashboardRestarted = $true
    Write-Output "DASHBOARD_RESTARTED_PID: $($dashProc.Id)"
}

# Step 5: Telegram if any restart happened
if ($restarted) {
    Write-Output "TELEGRAM: Bot was down, restarted. PID: $restartPid"
}
if ($dashboardRestarted) {
    Write-Output "TELEGRAM: Dashboard was down, restarted."
}
