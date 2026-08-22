$ErrorActionPreference = 'Continue'
Set-Location "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot"

# 1. Bot alive check (4h window)
$alive4h = Get-Process python -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -like '*kotak-neo-bot*' -and $_.StartTime -gt (Get-Date).AddHours(-4) } |
    Measure-Object | Select-Object -ExpandProperty Count
Write-Host "ALIVE_4H=$alive4h"

$aliveAll = Get-Process python -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -like '*kotak-neo-bot*' } |
    Measure-Object | Select-Object -ExpandProperty Count
Write-Host "ALIVE_ALL=$aliveAll"

# 2. Dashboard
$dash = 'DOWN'
try {
    $resp = Invoke-WebRequest -Uri 'http://localhost:8501/_stcore/health' -UseBasicParsing -TimeoutSec 5
    $dash = $resp.StatusCode
} catch {}
Write-Host "DASHBOARD=$dash"

# 3. Active log
$logFile = 'Logs\bot.log'
if (Test-Path $logFile) {
    $log = Get-Item $logFile
    $age = (Get-Date) - $log.LastWriteTime
    Write-Host "LOG_SIZE=$($log.Length) LOG_AGE=$([math]::Round($age.TotalSeconds,1))s"
} else {
    Write-Host "LOG=MISSING"
}

# 4. Stderr log
$errFile = 'Logs\bot_stderr.log'
if (Test-Path $errFile) {
    $e = Get-Item $errFile
    Write-Host "STDERR_SIZE=$($e.Length)"
    $errs = Select-String -Path $errFile -Pattern 'Traceback|FATAL|Killed|Exception' -ErrorAction SilentlyContinue | Select-Object -Last 3
    Write-Host "STDERR_ERR_SCAN=$($errs.Count)"
} else {
    Write-Host "STDERR=MISSING"
}

# 5. Bot log error scan
if (Test-Path $logFile) {
    $errBot = Select-String -Path $logFile -Pattern 'Traceback|FATAL|Killed' -ErrorAction SilentlyContinue | Select-Object -Last 3
    Write-Host "BOT_LOG_ERR_SCAN=$($errBot.Count)"
}

# 6. Paper state
$stateFile = 'data_cache\paper_state.json'
if (Test-Path $stateFile) {
    try {
        $ps = Get-Content $stateFile -Raw -Encoding UTF8 | ConvertFrom-Json
        Write-Host "PAPER_CASH=$($ps.cash) PNL=$($ps.realized_pnl) POS=$($ps.positions.Count) ORD=$($ps.orders.Count)"
    } catch {
        Write-Host "PAPER_STATE_PARSE_ERR"
    }
} else {
    Write-Host "PAPER_STATE=MISSING"
}

# 7. Market hours check
$now = Get-Date
$hour = $now.Hour
$dow = $now.DayOfWeek
$isWeekday = ($dow -ne 'Saturday' -and $dow -ne 'Sunday')
$isMarketHours = $isWeekday -and ($hour -ge 9) -and ($hour -lt 15 -or ($hour -eq 15 -and $now.Minute -le 30))
Write-Host "MKT_HOURS=$isMarketHours DOW=$dow"
