$ErrorActionPreference = 'Stop'
Set-Location "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot"

$now = Get-Date
$hour = (Get-Date -Format 'HH:mm')
$isMarketHours = ($now.DayOfWeek -ge 'Monday' -and $now.DayOfWeek -le 'Friday') -and ($hour -ge '09:00' -and $hour -lt '15:30')

Write-Host "=== Heartbeat Check ==="
Write-Host "Time: $now | Market hours: $isMarketHours"

# Step 1: Primary check (4h window + path filter)
$alive = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*kotak-neo-bot*' -and $_.StartTime -gt (Get-Date).AddHours(-4) } | Measure-Object | Select-Object -ExpandProperty Count
Write-Host "Primary check (4h window): $alive processes"

$restarted = $false
if ($alive -eq 0 -and $isMarketHours) {
    $alive2 = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*kotak-neo-bot*' } | Measure-Object | Select-Object -ExpandProperty Count
    Write-Host "Secondary check (no time filter): $alive2 processes"
    if ($alive2 -eq 0) {
        Write-Host "BOT DOWN - restarting..."
        $proc = Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "-u", "-m", "kotak_bot", "paper" -RedirectStandardOutput "bot_stdout.log" -RedirectStandardError "bot_stderr.log" -WindowStyle Hidden -PassThru
        Write-Host "Started PID: $($proc.Id)"
        $restarted = $true
    }
}

# Step 2: stderr error scan
$errCount = 0
if (Test-Path 'bot_stderr.log') {
    $errs = Select-String -Path 'bot_stderr.log' -Pattern 'Traceback|FATAL|Killed|Exception' -ErrorAction SilentlyContinue | Select-Object -Last 3
    if ($errs) { $errCount = $errs.Count }
}
Write-Host "Recent errors in stderr: $errCount"

# Step 3: dashboard health
$dash = 'unknown'
try {
    $resp = Invoke-WebRequest -Uri 'http://localhost:8501/_stcore/health' -UseBasicParsing -TimeoutSec 5
    $dash = $resp.StatusCode
} catch {
    $dash = "down: $($_.Exception.Message)"
}
Write-Host "Dashboard: $dash"

if ($dash -ne 200) {
    Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "-u", "-m", "streamlit", "run", "dashboard\app.py", "--server.port=8501", "--server.headless=true" -WindowStyle Hidden
    Write-Host "Dashboard restarted"
}

Write-Host "=== End Heartbeat ==="
