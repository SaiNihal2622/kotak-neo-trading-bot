$ErrorActionPreference = 'Stop'
Set-Location "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot"
$py = ".\.venv\Scripts\python.exe"

# 1. Check bot alive with 4h filter
$alive4 = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*kotak-neo-bot*' -and $_.StartTime -gt (Get-Date).AddHours(-4) } | Measure-Object | Select-Object -ExpandProperty Count
$aliveAll = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*kotak-neo-bot*' } | Measure-Object | Select-Object -ExpandProperty Count

# Get detailed PID info
$alivePids = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*kotak-neo-bot*' } | ForEach-Object { "$($_.Id)($([math]::Round((New-TimeSpan -Start $_.StartTime -End (Get-Date)).TotalMinutes,1))m)" }
$alivePidsStr = $alivePids -join ','

# Identify main bot PID (kotak_bot paper, not streamlit)
$mainBot = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -like '*kotak_bot*paper*' -and $_.CommandLine -notlike '*streamlit*' } | Select-Object -First 1
$botPid = if ($mainBot) { $mainBot.ProcessId } else { $null }

# 2. Check bot stderr log
$logFile = "bot_stderr.log"
$logSize = if (Test-Path $logFile) { (Get-Item $logFile).Length } else { 0 }
$logAgeMin = if (Test-Path $logFile) { [math]::Round((New-TimeSpan -Start (Get-Item $logFile).LastWriteTime -End (Get-Date)).TotalMinutes, 2) } else { -1 }
$errLines = if (Test-Path $logFile) { Select-String -Path $logFile -Pattern 'Traceback|FATAL|Killed|Exception' | Select-Object -Last 3 } else { @() }
$errCount = $errLines.Count

# 3. Check dashboard 8501 with single attempt
$dashStatus = $null
try {
    $resp = Invoke-WebRequest -Uri 'http://localhost:8501/_stcore/health' -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
    $dashStatus = [int]$resp.StatusCode
} catch {
    try {
        $resp = Invoke-WebRequest -Uri 'http://localhost:8501/_stcore/health' -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
        $dashStatus = [int]$resp.StatusCode
    } catch {
        $dashStatus = $null
    }
}

# Market hours check (Mon-Fri 9:00-15:30 IST)
$now = Get-Date
$dayOfWeek = $now.DayOfWeek
$hour = $now.Hour
$min = $now.Minute
$timeMin = $hour * 60 + $min
$mktOpen = 9 * 60
$mktClose = 15 * 60 + 30
$isWeekday = $dayOfWeek -ge [DayOfWeek]::Monday -and $dayOfWeek -le [DayOfWeek]::Friday
$mktHours = $isWeekday -and ($timeMin -ge $mktOpen -and $timeMin -lt $mktClose)

# Decision logic
$action = 'silent'
$dashAction = ''
$tgMsg = ''
$tgStatus = $null

if ($dashStatus -ne 200) {
    $dashAction = 'restart_dash'
    $action = 'restart_dash'
    $tgMsg = "[Mavis 24/7 04:10] Dashboard 8501 was down (status=$dashStatus), restarted streamlit (heartbeat tick 04:10)"
}

# Bot restart check (only during market hours)
if ($mktHours -and $alive4 -eq 0) {
    $secondCheck = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*kotak-neo-bot*' } | Measure-Object | Select-Object -ExpandProperty Count
    if ($secondCheck -eq 0) {
        $action = 'restart_bot'
        $tgMsg = "Bot was down, restarted."
    }
}

# Send Telegram if needed
if ($tgMsg) {
    $botToken = $null
    $chatId = $null
    if (Test-Path '.env') {
        Get-Content '.env' -ErrorAction SilentlyContinue | ForEach-Object {
            if ($_ -match '^TELEGRAM_BOT_TOKEN=(.+)$') { $botToken = $Matches[1] }
            elseif ($_ -match '^TELEGRAM_CHAT_ID=(.+)$') { $chatId = $Matches[1] }
        }
    }
    if ($botToken -and $chatId) {
        try {
            $tgResp = Invoke-RestMethod -Uri "https://api.telegram.org/bot$botToken/sendMessage" -Method Post -Body @{ chat_id = $chatId; text = $tgMsg } -TimeoutSec 10
            $tgStatus = if ($tgResp.ok) { 200 } else { 500 }
        } catch {
            $tgStatus = 500
        }
    }
}

# Update state file
$state = @{
    tc = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ss')
    err = 0
    alive4 = $alive4
    aliveAll = $aliveAll
    dash = $dashStatus
    dashAction = $dashAction
    mktHours = [bool]$mktHours
    action = $action
    botPid = $botPid
    alivePids = $alivePidsStr
    logSize = $logSize
    logAgeMin = $logAgeMin
    errs = $errCount
    lastErrLines = @($errLines | ForEach-Object { $_.Line })
    tgStatus = $tgStatus
} | ConvertTo-Json -Compress

$stateDir = "data_cache"
if (-not (Test-Path $stateDir)) { New-Item -ItemType Directory -Path $stateDir -Force | Out-Null }
Set-Content -Path "$stateDir/heartbeat_state.json" -Value $state -Encoding UTF8

# Output summary
$summary = @"
=== Heartbeat Mon 04:10 IST ===
botPid=$botPid alive4=$alive4 aliveAll=$aliveAll dash=$dashStatus mktHours=$mktHours action=$action
logSize=$logSize logAgeMin=$logAgeMin errs=$errCount tgStatus=$tgStatus
alivePids=$alivePidsStr
dashAction=$dashAction
"@
Write-Output $summary
