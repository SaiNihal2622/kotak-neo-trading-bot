$ErrorActionPreference = 'Continue'
Set-Location "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot"

# Step 1: Check if bot is alive using path filter + 4h window
$alive = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*kotak-neo-bot*' -and $_.StartTime -gt (Get-Date).AddHours(-4) } | Measure-Object | Select-Object -ExpandProperty Count
Write-Host "ALIVE_4H: $alive"

# Check market hours
$now = Get-Date
$ist = [TimeZoneInfo]::ConvertTime($now, [TimeZoneInfo]::FindSystemTimeZoneById('India Standard Time'))
$hour = $ist.Hour
$min = $ist.Minute
$timeMin = $hour * 60 + $min
$isWeekday = (Get-Date).DayOfWeek -ne 'Saturday' -and (Get-Date).DayOfWeek -ne 'Sunday'
$mktStart = 9 * 60
$mktEnd = 15 * 60 + 30
$MKT_HOURS = $isWeekday -and $timeMin -ge $mktStart -and $timeMin -le $mktEnd
Write-Host "IST: $($ist.ToString('HH:mm'))  MKT_HOURS: $MKT_HOURS  Weekday: $isWeekday"

# If alive=0 during market hours, do second check
if ($alive -eq 0 -and $MKT_HOURS) {
    $aliveAll = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*kotak-neo-bot*' } | Measure-Object | Select-Object -ExpandProperty Count
    Write-Host "ALIVE_ALL (2nd check): $aliveAll"
} else {
    $aliveAll = $alive
}

# Step 2: Check stderr log for errors
if (Test-Path 'bot_stderr.log') {
    $errLines = Select-String -Path 'bot_stderr.log' -Pattern 'Traceback|FATAL|Killed|Exception' | Select-Object -Last 3
    if ($errLines) {
        $errLines | ForEach-Object { Write-Host "ERR: $($_.Line)" }
    } else {
        Write-Host "STDERR_CLEAN"
    }
    $errFile = Get-Item 'bot_stderr.log'
    Write-Host "STDERR mtime: $($errFile.LastWriteTime) size: $($errFile.Length)B"
} else {
    Write-Host "NO_STDERR_LOG"
}

# Step 3: Check dashboard health
try {
    $resp = Invoke-WebRequest -Uri 'http://localhost:8501/_stcore/health' -UseBasicParsing -TimeoutSec 5
    Write-Host "DASH: $($resp.StatusCode)"
} catch {
    Write-Host "DASH_DOWN: $($_.Exception.Message)"
}

# Show recent bot.log if exists
if (Test-Path 'bot.log') {
    $botLog = Get-Item 'bot.log'
    Write-Host "BOT.LOG mtime: $($botLog.LastWriteTime.ToString('HH:mm:ss')) size: $($botLog.Length)B"
    Get-Content 'bot.log' -Tail 1 | ForEach-Object { Write-Host "LAST: $_" }
} else {
    Write-Host "NO_BOT_LOG"
}
