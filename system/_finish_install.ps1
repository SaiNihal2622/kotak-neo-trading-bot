# Final NSSM install — non-blocking, runs as Administrator.
# Called via: Start-Process powershell -Verb runas -ArgumentList "-File $path"
$ErrorActionPreference = 'Continue'
$nssm = 'C:\Tools\nssm\nssm-2.24\win64\nssm.exe'
$RepoRoot = 'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot'
$LogDir = Join-Path $RepoRoot 'Logs'
$ps = (Get-Command powershell.exe).Source
$botScript = Join-Path $RepoRoot 'system\run_bot.ps1'
$dashScript = Join-Path $RepoRoot 'system\run_dashboard.ps1'

# 1) Remove any pre-existing half-registered services
foreach ($svc in 'KotakBotPaper','KotakDashboard') {
  & $nssm stop $svc 2>$null | Out-Null
  & $nssm remove $svc confirm 2>$null | Out-Null
}
Start-Sleep -Seconds 2

# 2) Install KotakBotPaper
& $nssm install KotakBotPaper $ps "-NoProfile -ExecutionPolicy Bypass -File `"$botScript`"" 2>&1 | Out-Null
& $nssm set KotakBotPaper DisplayName "Kotak Neo Trading Bot (Paper)" 2>&1 | Out-Null
& $nssm set KotakBotPaper Description "Indian options paper-trading bot, NIFTY+BANKNIFTY, 2-3 lots. Auto-restart on crash." 2>&1 | Out-Null
& $nssm set KotakBotPaper AppDirectory $RepoRoot 2>&1 | Out-Null
& $nssm set KotakBotPaper Start SERVICE_AUTO_START 2>&1 | Out-Null
& $nssm set KotakBotPaper AppRestartDelay 5000 2>&1 | Out-Null
& $nssm set KotakBotPaper AppStdout (Join-Path $LogDir 'bot_stdout.log') 2>&1 | Out-Null
& $nssm set KotakBotPaper AppStderr (Join-Path $LogDir 'bot_stderr.log') 2>&1 | Out-Null
& $nssm set KotakBotPaper AppRotateFiles 1 2>&1 | Out-Null
& $nssm set KotakBotPaper AppRotateBytes 52428800 2>&1 | Out-Null
& $nssm set KotakBotPaper AppThrottle 5000 2>&1 | Out-Null
& $nssm set KotakBotPaper AppStopMethodConsole 1500 2>&1 | Out-Null

# 3) Install KotakDashboard
& $nssm install KotakDashboard $ps "-NoProfile -ExecutionPolicy Bypass -File `"$dashScript`"" 2>&1 | Out-Null
& $nssm set KotakDashboard DisplayName "Kotak Trading Bot Dashboard" 2>&1 | Out-Null
& $nssm set KotakDashboard Description "Streamlit dashboard on http://127.0.0.1:8501" 2>&1 | Out-Null
& $nssm set KotakDashboard AppDirectory $RepoRoot 2>&1 | Out-Null
& $nssm set KotakDashboard Start SERVICE_AUTO_START 2>&1 | Out-Null
& $nssm set KotakDashboard AppRestartDelay 5000 2>&1 | Out-Null
& $nssm set KotakDashboard AppStdout (Join-Path $LogDir 'dashboard_stdout.log') 2>&1 | Out-Null
& $nssm set KotakDashboard AppStderr (Join-Path $LogDir 'dashboard_stderr.log') 2>&1 | Out-Null
& $nssm set KotakDashboard AppRotateFiles 1 2>&1 | Out-Null
& $nssm set KotakDashboard AppRotateBytes 52428800 2>&1 | Out-Null
& $nssm set KotakDashboard AppThrottle 5000 2>&1 | Out-Null
& $nssm set KotakDashboard AppStopMethodConsole 1500 2>&1 | Out-Null

# 4) Start both
Start-Sleep -Seconds 2
& $nssm start KotakBotPaper 2>&1
& $nssm start KotakDashboard 2>&1
Start-Sleep -Seconds 5
Write-Host ""
Write-Host "=== STATUS ==="
& $nssm status KotakBotPaper
& $nssm status KotakDashboard

# 5) Register 5-min healthcheck scheduled task
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -File `"(Join-Path $RepoRoot 'system\healthcheck.ps1')`""
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
try {
  Unregister-ScheduledTask -TaskName 'KotakBotHealthcheck' -Confirm:$false -ErrorAction SilentlyContinue | Out-Null
  Register-ScheduledTask -TaskName 'KotakBotHealthcheck' -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
  Write-Host "Healthcheck scheduled task: KotakBotHealthcheck (5min)"
} catch {
  Write-Host "Healthcheck task FAILED: $($_.Exception.Message)"
}
Write-Host "DONE."
