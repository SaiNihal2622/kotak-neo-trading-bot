$ErrorActionPreference = 'Continue'
$projectDir = "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot"
Set-Location $projectDir
$py = ".\.venv\Scripts\python.exe"

# Step 1: Check bot alive (4h window)
$alive4 = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*kotak-neo-bot*' -and $_.StartTime -gt (Get-Date).AddHours(-4) } | Measure-Object | Select-Object -ExpandProperty Count
$aliveAll = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*kotak-neo-bot*' } | Measure-Object | Select-Object -ExpandProperty Count

# Get details of any bot procs
$botProcs = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*kotak-neo-bot*' } | Select-Object Id, StartTime, @{Name='AgeMin';Expression={[math]::Round(((Get-Date) - $_.StartTime).TotalMinutes,1)}}, Path

# Market hours check (9:00-15:30 IST Mon-Fri) - assume system clock is IST
$now = Get-Date
$hour = $now.Hour
$min = $now.Minute
$isWeekday = $now.DayOfWeek -ge [System.DayOfWeek]::Monday -and $now.DayOfWeek -le [System.DayOfWeek]::Friday
$marketMinutes = $hour * 60 + $min
$mktOpen = 9 * 60
$mktClose = 15 * 60 + 30
$mktHours = $isWeekday -and ($marketMinutes -ge $mktOpen) -and ($marketMinutes -lt $mktClose)

Write-Host "=== HEARTBEAT $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ==="
Write-Host "Hour: $hour Min: $min Weekday: $isWeekday MktHours: $mktHours"
Write-Host "Alive4h: $alive4 AliveAll: $aliveAll"
Write-Host "Bot Procs:"
if ($botProcs) { $botProcs | Format-Table -AutoSize | Out-String | Write-Host } else { Write-Host "  (none)" }

# Step 2: stderr log check
$errLog = "bot_stderr.log"
$errCount = 0
$errLines = ""
if (Test-Path $errLog) {
    $errSize = (Get-Item $errLog).Length
    $errAgeMin = [math]::Round(((Get-Date) - (Get-Item $errLog).LastWriteTime).TotalMinutes, 1)
    Write-Host "Stderr log: size=$errSize age=${errAgeMin}m"
    $errs = Select-String -Path $errLog -Pattern 'Traceback|FATAL|Killed|Exception' | Select-Object -Last 3
    if ($errs) {
        Write-Host "ERRORS FOUND:"
        $errs | ForEach-Object { Write-Host "  $($_.LineNumber): $($_.Line)" }
        $errCount = $errs.Count
        $errLines = ($errs | ForEach-Object { $_.Line }) -join " | "
    } else {
        Write-Host "Stderr: clean (no Traceback/FATAL/Killed/Exception)"
    }
} else {
    Write-Host "Stderr log: not found"
}

# Step 3: Dashboard health
$dashCode = 0
try {
    $dashResp = Invoke-WebRequest -Uri 'http://localhost:8501/_stcore/health' -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
    $dashCode = [int]$dashResp.StatusCode
} catch {
    $dashCode = 0
}
Write-Host "Dashboard: HTTP $dashCode"

# Step 3b: Restart dashboard if down
if ($dashCode -ne 200) {
    Write-Host "Dashboard down -> RESTART dashboard"
    Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "-u", "-m", "streamlit", "run", "dashboard\app.py", "--server.port=8501", "--server.headless=true" -WindowStyle Hidden
}

# Step 4 & 5: Restart decision
$action = "silent"
$restartPid = $null
if ($alive4 -eq 0) {
    if ($aliveAll -eq 0) {
        if ($mktHours) {
            Write-Host "MARKET HOURS + 0 bot procs (double-check) -> RESTART"
            $proc = Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "-u", "-m", "kotak_bot", "paper" -RedirectStandardOutput "bot_stdout.log" -RedirectStandardError "bot_stderr.log" -WindowStyle Hidden -PassThru
            $restartPid = $proc.Id
            $action = "restart"
        } else {
            Write-Host "After-hours + 0 bot procs (double-check) -> NO RESTART (silent)"
            $action = "silent_afterhours_down"
        }
    } else {
        Write-Host "First check 0 but second check found procs (false zero) -> NO RESTART"
        $action = "silent_false_zero"
    }
}

# Step 5: Telegram on restart
if ($action -eq "restart" -and $restartPid) {
    Write-Host "TELEGRAM: Bot was down, restarted. PID: $restartPid"
} else {
    Write-Host "Action: $action (no telegram)"
}

# Update state file
$stateDir = "data_cache"
if (-not (Test-Path $stateDir)) { New-Item -ItemType Directory -Path $stateDir -Force | Out-Null }
$ts = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
$state = @{
    ts = $ts
    err = $errCount
    alive4 = $alive4
    aliveAll = $aliveAll
    dash = $dashCode
    mktHours = $mktHours
    action = $action
    botPid = if ($botProcs) { ($botProcs | Select-Object -First 1).Id } else { 0 }
    botAge = if ($botProcs) { ($botProcs | Select-Object -First 1).AgeMin } else { 0 }
    restartPid = $restartPid
    lastErrLines = $errLines
}
$state | ConvertTo-Json | Set-Content -Path "$stateDir/heartbeat_state.json" -Encoding UTF8
Write-Host "State file updated."
