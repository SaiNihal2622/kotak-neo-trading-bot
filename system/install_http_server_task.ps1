# =============================================================================
# install_http_server_task.ps1 — Register HTTP server with Windows Task Scheduler
# so it auto-starts on user logon. Idempotent.
#
# Why Task Scheduler (not NSSM / sc.exe)?
#   NSSM and sc.exe ServiceMain-based services fail to start the PowerShell
#   entry script within the 30s startup window (Windows Event 7000/7009 timeouts
#   — the python.exe child needs longer to bind :8502 and respond to /health).
#   Task Scheduler's "At logon" trigger has no ServiceMain requirement and works
#   reliably for detached long-running scripts.
#
# Trade-off: this is per-user (triggered on user logon, not system boot).
#   For a 24/7 host: change trigger to "At startup" and run with highest privileges.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File system\install_http_server_task.ps1
#   powershell -ExecutionPolicy Bypass -File system\install_http_server_task.ps1 -Uninstall
# =============================================================================
[CmdletBinding()]
param(
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'
$TaskName = 'KotakHttpServer-Autostart'
$RepoRoot = 'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot'
$ScriptPath = Join-Path $RepoRoot 'system\run_http_server.ps1'

if ($Uninstall) {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Unregistered task: $TaskName"
    } else {
        Write-Host "Task $TaskName was not registered."
    }
    return
}

# Validate prerequisites
if (-not (Test-Path $ScriptPath)) {
    throw "Entry script not found: $ScriptPath"
}

# Build the action: powershell -ExecutionPolicy Bypass -WindowStyle Hidden -File <script>
$action = New-ScheduledTaskAction `
    -Execute 'powershell.exe' `
    -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -NoProfile -File `"$ScriptPath`"" `
    -WorkingDirectory $RepoRoot

# Trigger: at user logon. With Delay so we don't race with the bot at boot.
$trigger = New-ScheduledTaskTrigger -AtLogOn
$trigger.Delay = 'PT2M'  # wait 2 min after logon to let network/services settle

# Settings: restart on failure up to 3 times, every 1m. Don't set ExecutionTimeLimit
# so the http server can run forever.
# Note: RestartInterval minimum accepted by the underlying task XML is 1 minute.
$restartInterval = New-TimeSpan -Minutes 1
$noTimeLimit = New-TimeSpan -Seconds 0
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 3 -RestartInterval $restartInterval -ExecutionTimeLimit $noTimeLimit -MultipleInstances IgnoreNew

# Run as the current user (interactive session).
# If you want to run as SYSTEM, use -User 'SYSTEM' -RunLevel Highest.
$principal = New-ScheduledTaskPrincipal `
    -User $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

# Idempotent: if task already exists, replace it
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Updating existing task: $TaskName"
    Set-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal | Out-Null
} else {
    Write-Host "Creating new task: $TaskName"
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Description "Auto-starts the kotak-neo-bot HTTP server (:8502) at user logon. Provides /health, /metrics, /status for external monitoring." | Out-Null
}

Write-Host ""
Write-Host "Task '$TaskName' registered."
Write-Host "  Trigger:    At user logon (with 2min delay)"
Write-Host "  Action:     powershell $ScriptPath"
Write-Host "  Restart:    on failure, up to 3x every 30s"
Write-Host ""
Write-Host "To trigger now (without logging off/on):"
Write-Host "  Start-ScheduledTask -TaskName $TaskName"
Write-Host ""
Write-Host "To uninstall:"
Write-Host "  powershell -ExecutionPolicy Bypass -File $PSCommandPath -Uninstall"
