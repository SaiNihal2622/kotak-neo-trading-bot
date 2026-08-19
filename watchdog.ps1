# kotak-neo-bot Watchdog
# Monitors bot (Python process) + dashboard (port 8501). Auto-restarts if dead.
# Designed to run as a Windows Startup-folder task on user logon.

$ErrorActionPreference = 'Stop'
$project = 'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot'
$logFile = Join-Path $project 'logs\watchdog.log'

function Write-WLog {
    param([string]$msg)
    $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    Add-Content -Path $logFile -Value ("[" + $ts + "] " + $msg) -Encoding UTF8
}

$logDir = Split-Path $logFile
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

Write-WLog ("=== Watchdog started (PID " + $PID + ") ===")
Write-WLog ("Project: " + $project)
Write-WLog "Will check every 60s, restart bot/dashboard if dead"

$checkIntervalSec = 60
$restartCooldownSec = 30
$lastBotRestart = (Get-Date).AddSeconds(-$restartCooldownSec - 1)
$lastDashRestart = (Get-Date).AddSeconds(-$restartCooldownSec - 1)

while ($true) {
    try {
        # Check bot
        $botProcs = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -match 'kotak_bot' })
        $botAlive = ($botProcs.Count -gt 0)

        if (-not $botAlive) {
            $now = Get-Date
            $sinceLast = ($now - $lastBotRestart).TotalSeconds
            if ($sinceLast -ge $restartCooldownSec) {
                Write-WLog "ALERT: bot DEAD - invoking start_bot_detached.ps1"
                try {
                    $out = & "$project\start_bot_detached.ps1" 2>&1
                    Write-WLog ("  start_bot_detached.ps1 invoked (" + $out.Count + " lines)")
                    $lastBotRestart = $now
                    Start-Sleep -Seconds 30
                } catch {
                    Write-WLog ("  ERROR: " + $_.ToString())
                }
            } else {
                $rounded = [math]::Round($sinceLast, 0)
                Write-WLog ("Bot dead but within cooldown (" + $rounded + "s since last restart), skipping")
            }
        }

        # Check dashboard
        $dashAlive = $false
        try {
            $dashAlive = (Test-NetConnection -ComputerName 127.0.0.1 -Port 8501 -InformationLevel Quiet -WarningAction SilentlyContinue)
        } catch {
            $dashAlive = $false
        }

        if (-not $dashAlive) {
            $now = Get-Date
            $sinceLast = ($now - $lastDashRestart).TotalSeconds
            if ($sinceLast -ge $restartCooldownSec) {
                Write-WLog "ALERT: dashboard DOWN - invoking start_dashboard_detached.ps1"
                try {
                    $out = & "$project\start_dashboard_detached.ps1" 2>&1
                    Write-WLog ("  start_dashboard_detached.ps1 invoked (" + $out.Count + " lines)")
                    $lastDashRestart = $now
                    Start-Sleep -Seconds 15
                } catch {
                    Write-WLog ("  ERROR: " + $_.ToString())
                }
            } else {
                Write-WLog ("Dashboard down but within cooldown, skipping")
            }
        }

    } catch {
        Write-WLog ("Outer loop error: " + $_.ToString())
    }

    Start-Sleep -Seconds $checkIntervalSec
}
