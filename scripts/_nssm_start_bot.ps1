$ErrorActionPreference = "SilentlyContinue"
$nssm = "C:\Tools\nssm\nssm-2.24\win64\nssm.exe"
$logFile = "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\Logs\_orphan_kill.log"
$ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

# First kill the user-space bot (PIDs 18044, 7204, 2196, 17952) so NSSM can
# take over as the single source of truth (one bot only).
"[$ts] killing user-space bot procs 18044, 7204, 2196, 17952" | Out-File -FilePath $logFile -Append
foreach ($pid_kill in @(18044, 7204, 2196, 17952)) {
  $p = Get-CimInstance Win32_Process -Filter "ProcessId = $pid_kill" -ErrorAction SilentlyContinue
  if ($p) {
    "  -> taskkill /F /T /PID $pid_kill" | Out-File -FilePath $logFile -Append
    cmd /c "taskkill /F /T /PID $pid_kill" 2>&1 | Out-File -FilePath $logFile -Append
  }
}
Start-Sleep -Seconds 2

# Start KotakBotPaper NSSM
"[$ts] starting KotakBotPaper NSSM" | Out-File -FilePath $logFile -Append
& $nssm start KotakBotPaper 2>&1 | Out-File -FilePath $logFile -Append
Start-Sleep -Seconds 4
"[$ts] done" | Out-File -FilePath $logFile -Append
