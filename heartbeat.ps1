$ErrorActionPreference = 'Continue'
Set-Location "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot"

Write-Host "=== 1. Bot process check ==="
$bots = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.StartTime -gt (Get-Date).AddHours(-2) }
$count = ($bots | Measure-Object).Count
Write-Host "Python processes started in last 2h: $count"
$bots | Select-Object Id, ProcessName, StartTime, @{Name='Age_min';Expression={[math]::Round(((Get-Date) - $_.StartTime).TotalMinutes,1)}} | Format-Table -AutoSize

Write-Host ""
Write-Host "=== 2. Stderr log tail (last 30 lines) ==="
$log = "bot_stderr.log"
if (Test-Path $log) {
    Get-Content $log -Tail 30 -ErrorAction SilentlyContinue
} else {
    Write-Host "No bot_stderr.log file"
}

Write-Host ""
Write-Host "=== 3. Recent errors (Traceback|FATAL|Killed|Exception) ==="
if (Test-Path $log) {
    $errs = Select-String -Path $log -Pattern 'Traceback|FATAL|Killed|Exception' -ErrorAction SilentlyContinue | Select-Object -Last 3
    if ($errs) {
        $errs | ForEach-Object { Write-Host $_.Line }
    } else {
        Write-Host "No error patterns found"
    }
} else {
    Write-Host "No log file"
}

Write-Host ""
Write-Host "=== 4. Dashboard health (localhost:8501) ==="
try {
    $resp = Invoke-WebRequest -Uri "http://localhost:8501/_stcore/health" -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
    Write-Host "Dashboard status: $($resp.StatusCode)"
} catch {
    Write-Host "Dashboard DOWN: $($_.Exception.Message)"
}

Write-Host ""
Write-Host "=== 5. Market hours check ==="
$now = Get-Date
$dayOfWeek = $now.DayOfWeek
$hour = $now.Hour
$isWeekday = ($dayOfWeek -ne 'Saturday' -and $dayOfWeek -ne 'Sunday')
$marketOpen = $isWeekday -and ($hour -ge 9) -and ($hour -lt 15 -or ($hour -eq 15 -and $now.Minute -le 30))
Write-Host "Day: $dayOfWeek, Hour: $hour, Market hours: $marketOpen"
