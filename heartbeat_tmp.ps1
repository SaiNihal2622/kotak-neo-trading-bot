$ErrorActionPreference = 'Stop'
Set-Location "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot"
$py = ".\.venv\Scripts\python.exe"
$now = Get-Date
$istNow = $now.ToString("HH:mm")
$dayOfWeek = (Get-Date).DayOfWeek
$totalMin = ([int](Get-Date -Format "HH")) * 60 + [int](Get-Date -Format "mm")
$isWeekday = $dayOfWeek -ne 'Saturday' -and $dayOfWeek -ne 'Sunday'
$isMktHours = $isWeekday -and ($totalMin -ge 540 -and $totalMin -le 930)

Write-Host "=== Heartbeat $($now.ToString('yyyy-MM-dd HH:mm:ss')) IST ==="
Write-Host "IST=$istNow, DayOfWeek=$dayOfWeek, WEEKDAY=$isWeekday, MKT_HOURS=$isMktHours"

# Step 1: Bot alive check with path + 4h filter
$alive4 = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*kotak-neo-bot*' -and $_.StartTime -gt (Get-Date).AddHours(-4) } | Measure-Object | Select-Object -ExpandProperty Count
$aliveAll = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*kotak-neo-bot*' } | Measure-Object | Select-Object -ExpandProperty Count
Write-Host "alive4=$alive4, aliveAll=$aliveAll"

if ($alive4 -eq 0 -and $isMktHours) {
  $aliveAll2 = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*kotak-neo-bot*' } | Measure-Object | Select-Object -ExpandProperty Count
  Write-Host "Second check during MKT_HOURS: aliveAll2=$aliveAll2"
  if ($aliveAll2 -eq 0) {
    Write-Host "Both checks 0 during MKT_HOURS - would restart bot"
  } else {
    Write-Host "Second check found processes - likely 4h filter false zero, no restart"
  }
}

# Step 2: Stderr error check
$stderrHits = Select-String -Path 'bot_stderr.log' -Pattern 'Traceback|FATAL|Killed|Exception' -ErrorAction SilentlyContinue | Select-Object -Last 3
if ($stderrHits) {
  Write-Host "STDERR hits:"
  $stderrHits | ForEach-Object { Write-Host "  $($_.LineNumber): $($_.Line.Substring(0, [Math]::Min(200, $_.Line.Length)))" }
} else {
  Write-Host "STDERR_CLEAN: 0 Traceback/FATAL/Killed/Exception matches"
}

# Step 3: Dashboard health
try {
  $dashResp = Invoke-WebRequest -Uri 'http://localhost:8501/_stcore/health' -UseBasicParsing -TimeoutSec 5
  Write-Host "DASH 8501: HTTP $($dashResp.StatusCode) $($dashResp.StatusDescription)"
} catch {
  Write-Host "DASH 8501: DOWN - $($_.Exception.Message)"
}

# Step 4: Log freshness
$logInfo = Get-Item 'logs\bot.log' -ErrorAction SilentlyContinue
if ($logInfo) {
  $age = (Get-Date) - $logInfo.LastWriteTime
  Write-Host "logs\bot.log: size=$([Math]::Round($logInfo.Length/1MB,2))MB, age=$([Math]::Round($age.TotalSeconds,1))s, mtime=$($logInfo.LastWriteTime.ToString('HH:mm:ss'))"
}
