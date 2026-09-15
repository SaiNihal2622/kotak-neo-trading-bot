$ErrorActionPreference = "SilentlyContinue"
$logFile = "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\Logs\_orphan_kill.log"
$ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
"[$ts] killing PID 13924 (bot has OLD code, needs restart)" | Out-File -FilePath $logFile -Append
cmd /c "taskkill /F /T /PID 13924" 2>&1 | Out-File -FilePath $logFile -Append
# Also kill http_server (14748, 20424) since the new NSSM bot will respawn its own
foreach ($pid in @(14748, 20424)) {
  $p = Get-CimInstance Win32_Process -Filter "ProcessId = $pid" -ErrorAction SilentlyContinue
  if ($p) {
    cmd /c "taskkill /F /T /PID $pid" 2>&1 | Out-File -FilePath $logFile -Append
  }
}
Start-Sleep -Seconds 4
"[$ts] done" | Out-File -FilePath $logFile -Append
