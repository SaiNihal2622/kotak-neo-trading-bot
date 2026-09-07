# supervisor_loop.ps1 - SYSTEM-context watchdog for the Kotak Neo bot.
#
# Runs as a scheduled task registered to run as LocalSystem with HIGHEST
# privileges. Every 30 seconds, checks:
#   1. NSSM service KotakBotPaper - start if not running
#   2. NSSM service KotakQuantService - start if not running
#   3. Bot process - restart via NSSM if liveness.json is stale
#   4. Brain port 8503 - alert if down
#
# Logs to Logs/supervisor_loop.log
#
# Usage (auto-started by scheduled task "KotakSupervisor"):
#   powershell -NoProfile -ExecutionPolicy Bypass -File system\supervisor_loop.ps1

$ErrorActionPreference = 'Continue'
$ROOT = 'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot'
$LOG_DIR = Join-Path $ROOT 'Logs'
$NSSM = 'C:\Tools\nssm\nssm-2.24\win64\nssm.exe'
$LOG_FILE = Join-Path $LOG_DIR 'supervisor_loop.log'
$CHECK_INTERVAL_SEC = 30
$STALE_THRESHOLD_SEC = 180

if (-not (Test-Path $LOG_DIR)) {
    New-Item -ItemType Directory -Path $LOG_DIR -Force | Out-Null
}

function Log([string]$msg) {
    $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    $line = "[$ts] $msg"
    Write-Host $line
    Add-Content -Path $LOG_FILE -Value $line -Encoding UTF8
}

function Get-NssmStatus([string]$service) {
    try {
        $out = & sc.exe query $service 2>&1
        if ($LASTEXITCODE -ne 0) { return 'UNKNOWN' }
        $stdout = ($out | Out-String).ToUpper()
        if ($stdout -match 'STATE\s+:\s+\d+\s+RUNNING') { return 'RUNNING' }
        if ($stdout -match 'STATE\s+:\s+\d+\s+STOPPED') { return 'STOPPED' }
        if ($stdout -match 'STATE\s+:\s+\d+\s+START_PENDING') { return 'START_PENDING' }
        if ($stdout -match 'STATE\s+:\s+\d+\s+STOP_PENDING') { return 'STOP_PENDING' }
        return 'UNKNOWN'
    } catch {
        return 'UNKNOWN'
    }
}

function Start-NssmService([string]$service) {
    try {
        Log "[supervisor] starting NSSM service $service"
        $p = Start-Process -FilePath $NSSM -ArgumentList @('start', $service) -Wait -PassThru -NoNewWindow
        if ($p.ExitCode -eq 0) {
            Log "[supervisor] $service started OK (exit=0)"
            return $true
        } else {
            Log "[supervisor] $service start failed (exit=$($p.ExitCode))"
            return $false
        }
    } catch {
        Log "[supervisor] $service start error: $_"
        return $false
    }
}

function Get-BotPid() {
    $liv = Join-Path $ROOT 'data_cache\liveness.json'
    if (-not (Test-Path $liv)) { return $null }
    try {
        $d = Get-Content $liv -Raw | ConvertFrom-Json
        # liveness.json has a "pid" field, but $pid is read-only in PS.
        # Use a temp variable to extract.
        $proc_id = $d.pid
        return $proc_id
    } catch {
        return $null
    }
}

function Get-BotLivenessAge() {
    $liv = Join-Path $ROOT 'data_cache\liveness.json'
    if (-not (Test-Path $liv)) { return 999999 }
    try {
        $d = Get-Content $liv -Raw | ConvertFrom-Json
        if (-not $d.ts) { return 999999 }
        $last = [datetime]$d.ts
        $diff = ([datetime]::UtcNow - $last.ToUniversalTime()).TotalSeconds
        return $diff
    } catch {
        return 999999
    }
}

function Restart-BotViaNssm() {
    try {
        Log "[supervisor] restarting KotakBotPaper via NSSM (liveness stale or dead)"
        $p = Start-Process -FilePath $NSSM -ArgumentList @('restart', 'KotakBotPaper') -Wait -PassThru -NoNewWindow
        if ($p.ExitCode -eq 0) {
            Log "[supervisor] restart OK (exit=0)"
            return $true
        } else {
            Log "[supervisor] restart exit=$($p.ExitCode)"
            return $false
        }
    } catch {
        Log "[supervisor] restart error: $_"
        return $false
    }
}

function Test-BrainPort() {
    try {
        $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8503/health' -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop
        return ($r.StatusCode -eq 200)
    } catch {
        return $false
    }
}

function Run-Cycle() {
    param($cycle)
    # 1. Check NSSM KotakBotPaper
    $bot_nssm = Get-NssmStatus 'KotakBotPaper'
    if ($bot_nssm -ne 'RUNNING') {
        Log "[supervisor] cycle=$cycle KotakBotPaper NSSM is $bot_nssm - starting"
        $ok = Start-NssmService 'KotakBotPaper'
        if (-not $ok) {
            Log "[supervisor] cycle=$cycle NSSM start failed - falling back to direct start"
            $py = Join-Path $ROOT '.venv\Scripts\python.exe'
            $arglist = @('-m', 'kotak_bot', 'paper')
            Start-Process -FilePath $py -ArgumentList $arglist -WorkingDirectory $ROOT -WindowStyle Hidden
        }
    }

    # 2. Check NSSM KotakQuantService (brain)
    $brain_nssm = Get-NssmStatus 'KotakQuantService'
    if ($brain_nssm -ne 'RUNNING' -and $brain_nssm -ne 'START_PENDING') {
        Log "[supervisor] cycle=$cycle KotakQuantService NSSM is $brain_nssm - starting"
        Start-NssmService 'KotakQuantService'
    }

    # 3. Check bot liveness
    Start-Sleep -Seconds 5
    $age = Get-BotLivenessAge
    $bot_pid = Get-BotPid
    $age_int = [int]$age
    if ($age -gt $STALE_THRESHOLD_SEC) {
        Log "[supervisor] cycle=$cycle liveness is stale (age=$age_int s, pid=$bot_pid) - restarting bot"
        Restart-BotViaNssm
    }

    # 4. Check brain port
    if (-not (Test-BrainPort)) {
        Log "[supervisor] cycle=$cycle brain port 8503 not responding"
    }

    # Verbose status every 10 minutes
    if ($cycle % 20 -eq 0) {
        $pid_str = 'none'
        if ($bot_pid) { $pid_str = $bot_pid.ToString() }
        Log "[supervisor] cycle=$cycle OK | bot_nssm=$bot_nssm | brain_nssm=$brain_nssm | bot_pid=$pid_str | liveness_age=$age_int s"
    }
}

# Main loop
Log "=================================================="
Log "[supervisor] starting (interval=$CHECK_INTERVAL_SEC s, stale_threshold=$STALE_THRESHOLD_SEC s)"
$ctx = [Security.Principal.WindowsIdentity]::GetCurrent().Name
Log "[supervisor] context: $ctx"

$cycle = 0
while ($true) {
    $cycle = $cycle + 1
    try {
        Log "[supervisor] cycle=$cycle start"
        # 1. Check NSSM KotakBotPaper
        $svc_a = Get-NssmStatus 'KotakBotPaper'
        Log "[supervisor] cycle=$cycle KotakBotPaper nssm=$svc_a"
        if ($svc_a -ne 'RUNNING') {
            Log "[supervisor] cycle=$cycle starting KotakBotPaper"
            $ok_a = Start-NssmService 'KotakBotPaper'
            Log "[supervisor] cycle=$cycle start KotakBotPaper ok=$ok_a"
        }
        # 2. Check NSSM KotakQuantService (brain)
        $svc_b = Get-NssmStatus 'KotakQuantService'
        Log "[supervisor] cycle=$cycle KotakQuantService nssm=$svc_b"
        if ($svc_b -ne 'RUNNING' -and $svc_b -ne 'START_PENDING') {
            Log "[supervisor] cycle=$cycle starting KotakQuantService"
            $ok_b = Start-NssmService 'KotakQuantService'
            Log "[supervisor] cycle=$cycle start KotakQuantService ok=$ok_b"
        }
        # 3. Check bot liveness
        Start-Sleep -Seconds 5
        $age_x = Get-BotLivenessAge
        $bp = Get-BotPid
        $age_i = [int]$age_x
        Log "[supervisor] cycle=$cycle liveness age=$age_i bp=$bp"
        if ($age_x -gt $STALE_THRESHOLD_SEC) {
            Log "[supervisor] cycle=$cycle restarting bot"
            Restart-BotViaNssm
        }
        # 4. Check brain port
        $brain_ok = Test-BrainPort
        Log "[supervisor] cycle=$cycle brain_port=$brain_ok"
    } catch {
        Log "[supervisor] cycle=$cycle exception: $_"
    }
    Start-Sleep -Seconds $CHECK_INTERVAL_SEC
}
