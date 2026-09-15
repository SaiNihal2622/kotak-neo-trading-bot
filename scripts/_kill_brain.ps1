$ErrorActionPreference = "SilentlyContinue"
$logFile = "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\Logs\_orphan_kill.log"
$ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
"[$ts] killing brain python procs (will be NSSM-respawned with new code)" | Out-File -FilePath $logFile -Append
# Find and kill the brain python process (parent is NSSM 18684)
# We need admin to kill the python process (it's NSSM-owned)
$targets = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { ($_.CommandLine -eq '') -and ((Get-CimInstance Win32_Process -Filter "ProcessId = $($_.ParentProcessId)" -ErrorAction SilentlyContinue).Name -eq 'nssm.exe') -and ($_.ProcessId -ne 21904) }
foreach ($p in $targets) {
  "  target PID $($p.ProcessId) parent=$($p.ParentProcessId) started $($p.CreationDate.ToString('HH:mm:ss'))" | Out-File -FilePath $logFile -Append
  cmd /c "taskkill /F /T /PID $($p.ProcessId)" 2>&1 | Out-File -FilePath $logFile -Append
}
# Also try via the nssm: stop + start the service to force a clean respawn
"[$ts] stopping KotakQuantService NSSM" | Out-File -FilePath $logFile -Append
cmd /c "C:\Tools\nssm\nssm-2.24\win64\nssm.exe stop KotakQuantService" 2>&1 | Out-File -FilePath $logFile -Append
Start-Sleep -Seconds 3
"[$ts] starting KotakQuantService NSSM" | Out-File -FilePath $logFile -Append
cmd /c "C:\Tools\nssm\nssm-2.24\win64\nssm.exe start KotakQuantService" 2>&1 | Out-File -FilePath $logFile -Append
Start-Sleep -Seconds 5
"[$ts] done" | Out-File -FilePath $logFile -Append
