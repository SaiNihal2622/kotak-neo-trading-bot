$ErrorActionPreference = "SilentlyContinue"
$nssm = "C:\Tools\nssm\nssm-2.24\win64\nssm.exe"
$logFile = "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\Logs\_brain_restart.log"
$ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

# Stop the service, wait, start it back
"[$ts] stopping KotakQuantService..." | Out-File -FilePath $logFile -Append
& $nssm stop KotakQuantService 2>&1 | Out-File -FilePath $logFile -Append
Start-Sleep -Seconds 3
"[$ts] starting KotakQuantService..." | Out-File -FilePath $logFile -Append
& $nssm start KotakQuantService 2>&1 | Out-File -FilePath $logFile -Append
Start-Sleep -Seconds 2
"[$ts] done" | Out-File -FilePath $logFile -Append
