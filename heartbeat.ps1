$ErrorActionPreference = 'Stop'
Set-Location "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot"
$py = ".\.venv\Scripts\python.exe"

$now = Get-Date
$isMarketHours = $false
$dayOfWeek = (Get-Date).DayOfWeek
if ($dayOfWeek -ge 'Monday' -and $dayOfWeek -le 'Friday') {
  $hour = (Get-Date).Hour
  $min = (Get-Date).Minute
  $minutes = $hour * 60 + $min
  if ($minutes -ge 540 -and $minutes -le 930) { $isMarketHours = $true }
}
Write-Host "=== Heartbeat $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') IST | isMarketHours=$isMarketHours ==="

# Step 1: alive check (path + 4h window)
$alive = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*kotak-neo-bot*' -and $_.StartTime -gt (Get-Date).AddHours(-4) } | Measure-Object | Select-Object -ExpandProperty Count
$allBot = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*kotak-neo-bot*' } | Measure-Object | Select-Object -ExpandProperty Count
Write-Host "alive4=$alive allBot=$allBot"

$procs = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*kotak-neo-bot*' } | Select-Object Id, StartTime, @{N='AgeMin';E={[math]::Round(((Get-Date) - $_.StartTime).TotalMinutes,1)}}
$procs | Format-Table -AutoSize | Out-String | Write-Host

# Step 2: log error scan
Write-Host "--- ERROR SCAN ---"
$rootLog = ".\bot_stderr.log"
$botLog = ".\logs\bot_stderr.log"

if (Test-Path $rootLog) {
  $errs = Select-String -Path $rootLog -Pattern 'Traceback|FATAL|Killed|Exception' -ErrorAction SilentlyContinue | Select-Object -Last 3
  if ($errs) { $errs | ForEach-Object { Write-Host "  [root] $($_.LineNumber): $($_.Line.Substring(0, [Math]::Min(200, $_.Line.Length)))" } } else { Write-Host "  [root] no errors" }
}
if (Test-Path $botLog) {
  $errs2 = Select-String -Path $botLog -Pattern 'Traceback|FATAL|Killed|Exception' -ErrorAction SilentlyContinue | Select-Object -Last 3
  if ($errs2) { $errs2 | ForEach-Object { Write-Host "  [logs] $($_.LineNumber): $($_.Line.Substring(0, [Math]::Min(200, $_.Line.Length)))" } } else { Write-Host "  [logs] no errors" }
}

# Log growth
if (Test-Path $botLog) {
  $sz = (Get-Item $botLog).Length
  $lw = (Get-Item $botLog).LastWriteTime
  Write-Host "  logs/bot_stderr.log size=$sz lastWrite=$lw"
}
if (Test-Path $rootLog) {
  $sz2 = (Get-Item $rootLog).Length
  $lw2 = (Get-Item $rootLog).LastWriteTime
  Write-Host "  ./bot_stderr.log size=$sz2 lastWrite=$lw2 (spec reads)"
}

# Step 3: dashboard
Write-Host "--- DASHBOARD HEALTH ---"
try {
  $r = Invoke-WebRequest -Uri 'http://localhost:8501/_stcore/health' -TimeoutSec 5 -UseBasicParsing
  Write-Host "  HTTP $($r.StatusCode)"
} catch {
  Write-Host "  HTTP error: $($_.Exception.Message)"
}

# Step 4: decision
Write-Host "--- DECISION ---"
$restart = $false
if ($isMarketHours -and $alive -eq 0 -and $allBot -eq 0) {
  $restart = $true
  Write-Host "  market hours + double-check zero -> RESTART"
} elseif ($isMarketHours -and $alive -eq 0 -and $allBot -gt 0) {
  Write-Host "  alive4=0 but allBot=$allBot -> path/4h filter quirk, NO restart"
} else {
  Write-Host "  bot alive (alive4=$alive allBot=$allBot) -> no restart"
}
Write-Host "=== END HEARTBEAT ==="
