$ErrorActionPreference = 'Stop'
$py = ".\.venv\Scripts\python.exe"

# Market hours check
$now = Get-Date
$hour = $now.Hour
$minute = $now.Minute
$dow = $now.DayOfWeek
$isMarketHours = $false
if ($dow -ge 'Monday' -and $dow -le 'Friday') {
    if (($hour -eq 9 -and $minute -ge 0) -or ($hour -ge 10 -and $hour -lt 15) -or ($hour -eq 15 -and $minute -le 30)) {
        $isMarketHours = $true
    }
}
Write-Host "MARKET_HOURS=$isMarketHours (Hour=$hour Min=$minute DoW=$dow)"

# Step 1: Check alive with 4h window
$alive4h = Get-Process python -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -like '*kotak-neo-bot*' -and $_.StartTime -gt (Get-Date).AddHours(-4) } |
    Measure-Object | Select-Object -ExpandProperty Count
Write-Host "ALIVE_4H=$alive4h"

# Get full count for diagnostic
$aliveFull = Get-Process python -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -like '*kotak-neo-bot*' } |
    Measure-Object | Select-Object -ExpandProperty Count
Write-Host "ALIVE_FULL=$aliveFull"

# List processes if any
$procs = Get-Process python -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -like '*kotak-neo-bot*' }
foreach ($p in $procs) {
    $ageMin = [math]::Round(((Get-Date) - $p.StartTime).TotalMinutes, 1)
    Write-Host "  PID=$($p.Id) StartTime=$($p.StartTime) AgeMin=$ageMin Path=$($p.Path)"
}

# Step 2: Check stderr log for errors
$errMatches = Select-String -Path 'bot_stderr.log' -Pattern 'Traceback|FATAL|Killed|Exception' -ErrorAction SilentlyContinue | Select-Object -Last 3
if ($errMatches) {
    Write-Host "ERRORS_FOUND:"
    foreach ($m in $errMatches) { Write-Host "  $($m.LineNumber): $($m.Line)" }
} else {
    Write-Host "ERRORS=none"
}

# Step 3: Dashboard health
try {
    $resp = Invoke-WebRequest -Uri 'http://localhost:8501/_stcore/health' -UseBasicParsing -TimeoutSec 5
    Write-Host "DASH=$($resp.StatusCode)"
} catch {
    Write-Host "DASH=DOWN ($($_.Exception.Message))"
}

# Step 4 & 5: Restart decision (only echo, do not auto-restart in this script - controlled by cron host)
$needRestart = $false
if ($isMarketHours -and $alive4h -eq 0) {
    if ($aliveFull -eq 0) {
        $needRestart = $true
        Write-Host "DECISION=RESTART_BOTH_ZERO"
    } else {
        Write-Host "DECISION=NO_RESTART (4h=0 but full=$aliveFull - 4h filter false-zero)"
    }
} else {
    Write-Host "DECISION=NO_RESTART (alive4h=$alive4h, market=$isMarketHours)"
}

# Last few log lines for context
Write-Host "---LAST_LOG_LINES---"
if (Test-Path 'bot_stderr.log') {
    Get-Content 'bot_stderr.log' -Tail 5 -ErrorAction SilentlyContinue | ForEach-Object { Write-Host $_ }
} else {
    Write-Host "(no bot_stderr.log)"
}
