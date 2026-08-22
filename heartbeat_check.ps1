$ErrorActionPreference = 'Stop'
Set-Location "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot"

# Step 1: Bot alive check (path filter + 4h window)
$alive = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*kotak-neo-bot*' -and $_.StartTime -gt (Get-Date).AddHours(-4) } | Measure-Object | Select-Object -ExpandProperty Count
Write-Host "ALIVE_4H=$alive"
$aliveAll = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*kotak-neo-bot*' } | Measure-Object | Select-Object -ExpandProperty Count
Write-Host "ALIVE_ALL=$aliveAll"
$procs = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*kotak-neo-bot*' }
foreach ($p in $procs) {
  $uptime = (Get-Date) - $p.StartTime
  Write-Host "PID=$($p.Id) Started=$($p.StartTime) Uptime=$([int]$uptime.TotalMinutes)m"
}
Write-Host "---"

# Market hours check
$h = (Get-Date).Hour
$m = (Get-Date).Minute
$dayOfWeek = (Get-Date).DayOfWeek
$minsSinceMidnight = $h * 60 + $m
$mktOpen = 9 * 60
$mktClose = 15 * 60 + 30
$isWeekday = ($dayOfWeek -ne 'Saturday' -and $dayOfWeek -ne 'Sunday')
$isMktHours = $isWeekday -and ($minsSinceMidnight -ge $mktOpen) -and ($minsSinceMidnight -le $mktClose)
Write-Host "MKT_HOURS=$isMktHours (weekday=$isWeekday, $h`:$m)"

# Step 2: stderr error scan (canonical = logs\bot_stderr.log)
Write-Host "---"
Write-Host "STDERR SCAN:"
if (Test-Path 'logs\bot_stderr.log') {
  $logStderr = Get-Item 'logs\bot_stderr.log'
  Write-Host "logs\bot_stderr.log: age=$(([int]((Get-Date) - $logStderr.LastWriteTime).TotalMinutes))m, size=$([int]($logStderr.Length/1024))KB"
  $errors2 = Select-String -Path 'logs\bot_stderr.log' -Pattern 'Traceback|FATAL|Killed|Exception' | Select-Object -Last 3
  if ($errors2) {
    Write-Host "LAST 3 ERROR LINES (logs\bot_stderr.log):"
    $errors2 | ForEach-Object { Write-Host "L$($_.LineNumber): $($_.Line)" }
  } else {
    Write-Host "NO_RECENT_ERRORS"
  }
} else {
  Write-Host "NO_LOGS_STDERR"
}

# Step 3: Dashboard health
Write-Host "---"
Write-Host "DASHBOARD CHECK:"
try {
  $resp = Invoke-WebRequest -Uri 'http://localhost:8501/_stcore/health' -UseBasicParsing -TimeoutSec 5
  Write-Host "DASHBOARD_HTTP=$($resp.StatusCode)"
} catch {
  Write-Host "DASHBOARD_DOWN: $($_.Exception.Message)"
}

# bot.log freshness + last heartbeats
Write-Host "---"
Write-Host "BOT LOG:"
if (Test-Path 'logs\bot.log') {
  $log = Get-Item 'logs\bot.log'
  Write-Host "logs\bot.log: age=$(([int]((Get-Date) - $log.LastWriteTime).TotalMinutes))m, size=$([int]($log.Length/1024))KB"
  Write-Host "LAST 5 HEARTBEATS:"
  Get-Content 'logs\bot.log' -Tail 100 | Select-String -Pattern 'tick_count|heartbeat' | Select-Object -Last 5 | ForEach-Object { Write-Host $_.Line }
} else {
  Write-Host "NO_BOT_LOG"
}
