# =============================================================================
# healthcheck.ps1 — Cron-friendly check. Exits 0 if healthy, 1 if degraded.
# Intended to be run every 5 min by a cron / scheduled task.
# Sends Telegram alert on state changes (alive->dead, dead->alive, restart).
# =============================================================================
$ErrorActionPreference = 'Continue'
$RepoRoot = 'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot'
$LogDir   = Join-Path $RepoRoot 'Logs'
$StateFile = Join-Path $RepoRoot 'data_cache\healthcheck_state.json'
$BotLog = Join-Path $LogDir 'bot_stderr.log'
$DashboardLog = Join-Path $LogDir 'dashboard_stderr.log'

# --- Telegram config (load from .env) ---
$EnvFile = Join-Path $RepoRoot '.env'
if (Test-Path $EnvFile) {
  Get-Content $EnvFile | ForEach-Object {
    if ($_ -match '^\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.+?)\s*$') {
      $name = $matches[1]; $val = $matches[2]
      Set-Item -Path "Env:$name" -Value $val -ErrorAction SilentlyContinue
    }
  }
}
$tgToken = $env:TELEGRAM_BOT_TOKEN
$tgChat  = $env:TELEGRAM_CHAT_ID

function Send-Telegram([string]$text) {
  if (-not $tgToken -or -not $tgChat) { return }
  try {
    $uri = "https://api.telegram.org/bot${tgToken}/sendMessage"
    $body = @{ chat_id = $tgChat; text = $text; parse_mode = 'Markdown' } | ConvertTo-Json -Compress
    Invoke-RestMethod -Uri $uri -Method Post -ContentType 'application/json' -Body $body -TimeoutSec 5 | Out-Null
  } catch { }
}

# --- State ---
$state = @{
  last_alive    = $null
  last_alert_ts = 0
  last_pid      = $null
}
if (Test-Path $StateFile) {
  try { $state = Get-Content $StateFile -Raw | ConvertFrom-Json } catch { }
}

# --- Bot alive check ---
$botProcs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'kotak_bot' }
$botAlive = $botProcs.Count -ge 1
$botPid = if ($botProcs.Count -gt 0) { $botProcs[0].ProcessId } else { 0 }

# --- Dashboard alive check ---
$dashAlive = $false
try {
  $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8501/' -UseBasicParsing -TimeoutSec 3
  $dashAlive = ($r.StatusCode -eq 200)
} catch { $dashAlive = $false }

# --- Determine status ---
$now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
$prevAlive = $state.last_alive
$prevPid   = $state.last_pid

# State transitions
$wasAlive = ($prevAlive -eq $true)
$justDied = $wasAlive -and -not $botAlive
$justBorn = -not $wasAlive -and $botAlive
$restarted = ($botAlive -and $prevPid -and ($botPid -ne $prevPid))

# Throttle alerts: max 1 per 10 min
$alertThrottle = 600
$canAlert = ($now - $state.last_alert_ts) -gt $alertThrottle

# --- Log activity check (last 60s) ---
$logFresh = $false
if (Test-Path $BotLog) {
  $age = ((Get-Date) - (Get-Item $BotLog).LastWriteTime).TotalSeconds
  $logFresh = ($age -lt 120)
}

# --- Build report ---
$lines = @()
$lines += "🤖 *KotakBot health* — $(Get-Date -Format 'HH:mm:ss IST')"
$lines += "Bot PID:    $($botPid)"
$lines += "Bot alive:  $($botAlive)"
$lines += "Dashboard:  $($dashAlive)"
$lines += "Log fresh:  $($logFresh)"

if ($justDied -and $canAlert) {
  $lines += ""
  $lines += "🚨 *BOT WENT DOWN* — last PID $($prevPid) is no longer alive."
  Send-Telegram ($lines -join "`n")
  $state.last_alert_ts = $now
} elseif ($justBorn -and $canAlert) {
  $lines += ""
  $lines += "✅ *BOT BACK UP* — new PID $($botPid)."
  Send-Telegram ($lines -join "`n")
  $state.last_alert_ts = $now
} elseif ($restarted -and $canAlert) {
  $lines += ""
  $lines += "♻️ *BOT RESTARTED* — old PID $($prevPid) → new PID $($botPid)."
  Send-Telegram ($lines -join "`n")
  $state.last_alert_ts = $now
} elseif (-not $botAlive -and $canAlert) {
  $lines += ""
  $lines += "🚨 *BOT STILL DOWN* — no kotak_bot process for $($now - $state.last_alert_ts)s."
  Send-Telegram ($lines -join "`n")
  $state.last_alert_ts = $now
} elseif (-not $dashAlive -and $canAlert) {
  Send-Telegram "🚨 *Dashboard DOWN* at $(Get-Date -Format 'HH:mm:ss IST') — http://127.0.0.1:8501 not responding."
  $state.last_alert_ts = $now
}

# Persist
$state.last_alive = $botAlive
$state.last_pid   = $botPid
$state | ConvertTo-Json -Compress | Set-Content -Path $StateFile -Encoding UTF8

# Console output (for cron logs)
Write-Host ($lines -join "`n")

# Exit code: 0 if healthy, 1 if degraded
if ($botAlive -and $dashAlive) { exit 0 } else { exit 1 }
