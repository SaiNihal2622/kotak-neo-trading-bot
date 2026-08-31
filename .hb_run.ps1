$ErrorActionPreference = 'Stop'
$py = ".\.venv\Scripts\python.exe"

# 1. Alive check (path + 4h)
$alive4 = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*kotak-neo-bot*' -and $_.StartTime -gt (Get-Date).AddHours(-4) } | Measure-Object | Select-Object -ExpandProperty Count
$aliveAll = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*kotak-neo-bot*' } | Measure-Object | Select-Object -ExpandProperty Count

# Show context: which python procs are alive
$pyProcs = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*kotak-neo-bot*' } | Select-Object Id, StartTime, @{N='AgeMin';E={[math]::Round(((Get-Date) - $_.StartTime).TotalMinutes, 1)}}

# Market hours check
$now = Get-Date
$dayOfWeek = (Get-Date).DayOfWeek
$isWeekday = $dayOfWeek -ne 'Saturday' -and $dayOfWeek -ne 'Sunday'
$hour = $now.Hour; $minute = $now.Minute
$istMinutes = $hour * 60 + $minute
$mktOpen = $isWeekday -and ($istMinutes -ge 540 -and $istMinutes -le 930)  # 9:00 - 15:30

Write-Output "ALIVE4=$alive4  ALIVE_ALL=$aliveAll  MKT_HOURS=$mktOpen  WEEKDAY=$isWeekday  NOW=$now"
Write-Output "PYTHON PROCS:"
$pyProcs | Format-Table -AutoSize | Out-String | Write-Output

# 2. Stderr check (prefer logs\bot_stderr.log per memory; fallback to root)
$errFile = $null
if (Test-Path 'logs\bot_stderr.log') { $errFile = 'logs\bot_stderr.log' }
elseif (Test-Path 'bot_stderr.log') { $errFile = 'bot_stderr.log' }
$errCount = 0
$errLines = @()
if ($errFile) {
    $errLines = Select-String -Path $errFile -Pattern 'Traceback|FATAL|Killed|Exception' -ErrorAction SilentlyContinue | Select-Object -Last 3
    $errCount = ($errLines | Measure-Object).Count
    Write-Output "ERR_FILE=$errFile  ERR_COUNT=$errCount"
    if ($errCount -gt 0) { $errLines | ForEach-Object { Write-Output ("ERR: " + $_.Line) } }
} else {
    Write-Output "ERR_FILE=NONE"
}

# 3. Dashboard check
try {
    $resp = Invoke-WebRequest -Uri 'http://localhost:8501/_stcore/health' -UseBasicParsing -TimeoutSec 5
    Write-Output "DASH_8501=HTTP $($resp.StatusCode)"
} catch {
    Write-Output "DASH_8501=DOWN ($($_.Exception.Message))"
}

# bot.log freshness
if (Test-Path 'logs\bot.log') {
    $logAge = (Get-Date) - (Get-Item 'logs\bot.log').LastWriteTime
    Write-Output "BOT_LOG_AGE=$([math]::Round($logAge.TotalSeconds,1))s  SIZE=$((Get-Item 'logs\bot.log').Length)B"
} else {
    Write-Output "BOT_LOG=MISSING"
}
