$ErrorActionPreference = 'Stop'
$nssm = 'C:\Tools\nssm\nssm-2.24\win64\nssm.exe'
$RepoRoot = 'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot'
$LogDir = Join-Path $RepoRoot 'Logs'

# 1) Stop both services first (in case they're in Paused state)
& $nssm stop KotakBotPaper 2>$null
& $nssm stop KotakDashboard 2>$null
Start-Sleep -Seconds 3

# 2) Make sure config is correct
$ps = (Get-Command powershell.exe).Source
$botScript = Join-Path $RepoRoot 'system\run_bot.ps1'
$dashScript = Join-Path $RepoRoot 'system\run_dashboard.ps1'

& $nssm set KotakBotPaper Application $ps "-NoProfile -ExecutionPolicy Bypass -File `"$botScript`"" | Out-Null
& $nssm set KotakBotPaper AppDirectory $RepoRoot | Out-Null
& $nssm set KotakBotPaper Start SERVICE_AUTO_START | Out-Null
& $nssm set KotakBotPaper AppRestartDelay 5000 | Out-Null
& $nssm set KotakBotPaper AppThrottle 5000 | Out-Null
& $nssm set KotakBotPaper AppStdout (Join-Path $LogDir 'bot_stdout.log') | Out-Null
& $nssm set KotakBotPaper AppStderr (Join-Path $LogDir 'bot_stderr.log') | Out-Null
& $nssm set KotakBotPaper AppRotateFiles 1 | Out-Null
& $nssm set KotakBotPaper AppRotateBytes 52428800 | Out-Null

& $nssm set KotakDashboard Application $ps "-NoProfile -ExecutionPolicy Bypass -File `"$dashScript`"" | Out-Null
& $nssm set KotakDashboard AppDirectory $RepoRoot | Out-Null
& $nssm set KotakDashboard Start SERVICE_AUTO_START | Out-Null
& $nssm set KotakDashboard AppRestartDelay 5000 | Out-Null
& $nssm set KotakDashboard AppThrottle 5000 | Out-Null
& $nssm set KotakDashboard AppStdout (Join-Path $LogDir 'dashboard_stdout.log') | Out-Null
& $nssm set KotakDashboard AppStderr (Join-Path $LogDir 'dashboard_stderr.log') | Out-Null
& $nssm set KotakDashboard AppRotateFiles 1 | Out-Null
& $nssm set KotakDashboard AppRotateBytes 52428800 | Out-Null

# 3) Start them
Write-Host "Starting KotakBotPaper..."
& $nssm start KotakBotPaper
Write-Host "Starting KotakDashboard..."
& $nssm start KotakDashboard
Start-Sleep -Seconds 8
Write-Host ""
Write-Host "=== Status ==="
& $nssm status KotakBotPaper
& $nssm status KotakDashboard
