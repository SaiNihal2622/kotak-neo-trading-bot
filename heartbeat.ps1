$ErrorActionPreference = "SilentlyContinue"
$root = 'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot'
$logPath = Join-Path $root 'bot_stderr.log'
$stateDir = Join-Path $root 'data_cache'
$stateFile = Join-Path $stateDir 'heartbeat_state.json'

# Market hours (local time; server is IST)
$now = Get-Date
$isWeekday = $now.DayOfWeek -ne 'Saturday' -and $now.DayOfWeek -ne 'Sunday'
$mkt = $isWeekday -and (($now.Hour -gt 9) -or ($now.Hour -eq 9 -and $now.Minute -ge 0)) -and (($now.Hour -lt 15) -or ($now.Hour -eq 15 -and $now.Minute -le 30))

# 1) Bot alive (4h filter)
$alive4 = @(Get-Process python | Where-Object { $_.Path -like '*kotak-neo-bot*' -and $_.StartTime -gt (Get-Date).AddHours(-4) }).Count
$allPy  = @(Get-Process python).Count
$botProcs = @(Get-Process python | Where-Object { $_.Path -like '*kotak-neo-bot*' } | Sort-Object StartTime -Descending)
$botPid = 0
$botAge = 0
if ($botProcs.Count -gt 0) {
  $botPid = $botProcs[0].Id
  $botAge = [math]::Round(((Get-Date) - $botProcs[0].StartTime).TotalMinutes, 1)
}

# Double-check on dead during market hours
$restart = $false
$restartReason = ''
if ($mkt -and $alive4 -eq 0) {
  Start-Sleep -Seconds 2
  $alive4Retry = @(Get-Process python | Where-Object { $_.Path -like '*kotak-neo-bot*' }).Count
  if ($alive4Retry -eq 0) { $restart = $true; $restartReason = 'alive4=0 and retry=0 during market' }
  else { $alive4 = $alive4Retry }
}

# 2) Bot stderr log
$logSize = 0
$logAgeMin = 0
$errCount = 0
$errLines = @()
if (Test-Path $logPath) {
  $logInfo = Get-Item $logPath
  $logSize = $logInfo.Length
  $logAgeMin = [math]::Round(((Get-Date) - $logInfo.LastWriteTime).TotalMinutes, 1)
  $matches = @(Select-String -Path $logPath -Pattern 'Traceback|FATAL|Killed|Exception' -ErrorAction SilentlyContinue | Select-Object -Last 3)
  $errCount = $matches.Count
  foreach ($m in $matches) { $errLines += $m.Line.Substring(0, [Math]::Min(200, $m.Line.Length)) }
}

# 3) Dashboard
$dash = 0
$dashMsg = 'ERR'
try {
  $r = Invoke-WebRequest 'http://localhost:8501/_stcore/health' -UseBasicParsing -TimeoutSec 3
  $dash = [int]$r.StatusCode
  $dashMsg = $dash
} catch {
  $dash = 0
  $dashMsg = 'ERR'
}

# 4) Bot restart (market hours only)
if ($restart -and $mkt) {
  $py = Join-Path $root '.venv\Scripts\python.exe'
  if (Test-Path $py) {
    $p = Start-Process -FilePath $py -ArgumentList '-u','-m','kotak_bot','paper' `
      -RedirectStandardOutput 'bot_stdout.log' -RedirectStandardError 'bot_stderr.log' -WindowStyle Hidden -PassThru
    $restartReason = "$restartReason; spawned PID=$($p.Id)"
  }
}

# 5) State file
if (-not (Test-Path $stateDir)) { New-Item -ItemType Directory -Path $stateDir -Force | Out-Null }
$state = @{
  ts = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ss')
  mkt = $mkt
  alive4 = $alive4
  aliveAll = $allPy
  dash = $dash
  botPid = $botPid
  botAgeMin = $botAge
  logSize = $logSize
  logAgeMin = $logAgeMin
  errCount = $errCount
  errLines = $errLines
  restart = $restart
  restartReason = $restartReason
}
$state | ConvertTo-Json -Compress | Out-File -FilePath $stateFile -Encoding UTF8

# 6) Telegram (only on actual restart)
if ($restart -and $mkt) {
  $credFile = Join-Path $root 'config\credentials.env'
  $tgToken = ''
  $tgChat = '8537408638'
  if (Test-Path $credFile) {
    Get-Content $credFile | ForEach-Object {
      if ($_ -match '^\s*TELEGRAM_BOT_TOKEN\s*=\s*"?([^"]+)"?\s*$') { $tgToken = $Matches[1] }
    }
  }
  if ($tgToken) {
    $msg = "Bot was down, restarted. PID: $botPid. Reason: $restartReason"
    $body = @{ chat_id = $tgChat; text = $msg } | ConvertTo-Json -Compress
    try { Invoke-RestMethod -Uri "https://api.telegram.org/bot$tgToken/sendMessage" -Method Post -ContentType 'application/json' -Body $body -TimeoutSec 10 | Out-Null } catch {}
  }
}

# Status line
$hhmm = (Get-Date).ToString('HH:mm')
$line = "[$hhmm] MKT=$($mkt.ToString().ToLower()) alive4=$alive4/$allPy dash=$dashMsg log=$($logSize)B age=$($logAgeMin)m err=$errCount PID=$botPid age=$($botAge)m"
Write-Output $line
