$ErrorActionPreference = 'Stop'
$now = Get-Date
$istNow = $now.ToUniversalTime().AddHours(5.5)
$hour = $istNow.Hour
$min = $istNow.Minute
$dayOfWeek = $istNow.DayOfWeek
$mktHours = ($dayOfWeek -ne 'Saturday' -and $dayOfWeek -ne 'Sunday') -and (($hour -gt 9) -or ($hour -eq 9 -and $min -ge 0)) -and (($hour -lt 15) -or ($hour -eq 15 -and $min -le 30))

# Step 1: bot alive check (4h filter)
$alive4 = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*kotak-neo-bot*' -and $_.StartTime -gt (Get-Date).AddHours(-4) } | Measure-Object | Select-Object -ExpandProperty Count
$aliveAll = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*kotak-neo-bot*' } | Measure-Object | Select-Object -ExpandProperty Count

$botDown = $false
if ($alive4 -eq 0 -and $mktHours) {
    $aliveAll2 = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*kotak-neo-bot*' } | Measure-Object | Select-Object -ExpandProperty Count
    if ($aliveAll2 -eq 0) { $botDown = $true }
    $aliveAll = $aliveAll2
}

# Step 2: stderr log errors
$errLines = @()
if (Test-Path 'bot_stderr.log') {
    $matches = Select-String -Path 'bot_stderr.log' -Pattern 'Traceback|FATAL|Killed|Exception' -ErrorAction SilentlyContinue | Select-Object -Last 3
    if ($matches) { $errLines = $matches | ForEach-Object { $_.Line } }
}

# Step 3: dashboard health
$dash = $null
try {
    $dash = Invoke-WebRequest -Uri 'http://localhost:8501/_stcore/health' -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
} catch { $dash = $null }
$dashStatus = if ($dash) { $dash.StatusCode } else { 0 }
$dashDown = ($dashStatus -ne 200)

$action = 'silent'
$restartReason = ''
$telegramMsg = ''

if ($dashDown) {
    $action = 'restart-dashboard'
    $restartReason = "dashboard down (HTTP $dashStatus)"
    try {
        Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "-u","-m","streamlit","run","dashboard\app.py","--server.port=8501","--server.headless=true" -WindowStyle Hidden
        $telegramMsg = "Dashboard was down (HTTP $dashStatus), restarted."
    } catch {
        $telegramMsg = "Dashboard restart FAILED: $_"
    }
}

if ($botDown -and $mktHours) {
    $action = 'restart-bot'
    $restartReason = 'both alive checks returned 0 during market hours'
    try {
        $proc = Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "-u","-m","kotak_bot","paper" -RedirectStandardOutput "bot_stdout.log" -RedirectStandardError "bot_stderr.log" -WindowStyle Hidden -PassThru
        $telegramMsg = "Bot was down, restarted. PID: $($proc.Id)"
    } catch {
        $telegramMsg = "Bot restart FAILED: $_"
    }
}

if ($errLines.Count -gt 0 -and $action -eq 'silent') {
    $action = 'errors-detected'
}

# State file write
$stateDir = 'data_cache'
if (-not (Test-Path $stateDir)) { New-Item -ItemType Directory -Path $stateDir | Out-Null }
$botProc = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*kotak-neo-bot*' -and $_.StartTime -gt (Get-Date).AddHours(-4) } | Select-Object -First 1
$state = @{
    tc = (Get-Date).ToString('o')
    err = $errLines.Count
    alive4 = $alive4
    aliveAll = $aliveAll
    dash = $dashStatus
    mktHours = $mktHours
    action = $action
    botPid = if ($botProc) { $botProc.Id } else { 0 }
    botAgeMin = if ($botProc) { [math]::Round(((Get-Date) - $botProc.StartTime).TotalMinutes, 1) } else { 0 }
    logSize = if (Test-Path 'bot_stderr.log') { (Get-Item 'bot_stderr.log').Length } else { 0 }
    logAgeMin = if (Test-Path 'bot_stderr.log') { [math]::Round(((Get-Date) - (Get-Item 'bot_stderr.log').LastWriteTime).TotalMinutes, 1) } else { -1 }
    lastErrLines = $errLines
    restartReason = $restartReason
}
$state | ConvertTo-Json -Compress | Set-Content -Path "$stateDir/heartbeat_state.json" -Encoding UTF8

Write-Host "tick=$($state.tc) mktHours=$mktHours alive4=$alive4 aliveAll=$aliveAll dash=$dashStatus errors=$($errLines.Count) action=$action restartReason='$restartReason'"
if ($errLines.Count -gt 0) {
    Write-Host "---ERR LINES---"
    $errLines | ForEach-Object { Write-Host $_ }
}
if ($telegramMsg) { Write-Host "TELEGRAM: $telegramMsg" }
