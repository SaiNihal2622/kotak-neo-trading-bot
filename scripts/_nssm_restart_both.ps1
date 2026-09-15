# Full restart: brain + bot, both via NSSM
$ErrorActionPreference = "SilentlyContinue"
$nssm = "C:\Tools\nssm\nssm-2.24\win64\nssm.exe"
$root = "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot"
$logFile = "$root\Logs\_orphan_kill.log"
$ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
function logm($msg) { "[$ts] $msg" | Out-File -FilePath $logFile -Append; Write-Host $msg }

logm "=== FULL NSSM RESTART (brain + bot) ==="

# Stop both
logm "stopping KotakQuantService"
& $nssm stop KotakQuantService 2>&1 | Out-File -FilePath $logFile -Append
logm "stopping KotakBotPaper"
& $nssm stop KotakBotPaper 2>&1 | Out-File -FilePath $logFile -Append
Start-Sleep -Seconds 3

# Start both
logm "starting KotakQuantService"
& $nssm start KotakQuantService 2>&1 | Out-File -FilePath $logFile -Append
logm "starting KotakBotPaper"
& $nssm start KotakBotPaper 2>&1 | Out-File -FilePath $logFile -Append
Start-Sleep -Seconds 4

logm "=== NSSM restart done ==="
