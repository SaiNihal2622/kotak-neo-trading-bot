$ErrorActionPreference = "SilentlyContinue"
$nssm = "C:\Tools\nssm\nssm-2.24\win64\nssm.exe"
$logFile = "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\Logs\_orphan_kill.log"
$ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

# Kill the Aug 27 orphan python processes (PID 10184, 10828) which are
# NSSM-parented (KotakBotPaper) and running OLD pre-fix code that crashes
# on Order() with UnboundLocalError. The live bot (PID 18044/7204) is the
# real one. The orphan was created Aug 27 and has been squatting on
# liveness.json ever since, causing the "FETCH ERROR" pill + race.
"[$ts] killing orphan bot procs 10184, 10828" | Out-File -FilePath $logFile -Append
$procs = Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -eq 10184 -or $_.ProcessId -eq 10828 }
foreach ($p in $procs) {
  $pid_kill = $p.ProcessId
  $parent = $p.ParentProcessId
  $cmd = "taskkill /F /T /PID $pid_kill"
  "  -> taskkill /F /T /PID $pid_kill (parent=$parent)" | Out-File -FilePath $logFile -Append
  cmd /c $cmd 2>&1 | Out-File -FilePath $logFile -Append
}

Start-Sleep -Seconds 2
$still = Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -eq 10184 -or $_.ProcessId -eq 10828 }
if ($still) {
  "  STILL ALIVE - need admin UAC" | Out-File -FilePath $logFile -Append
} else {
  "  killed OK" | Out-File -FilePath $logFile -Append
}

# Also stop the KotakBotPaper NSSM service so it doesn't re-spawn the orphan
"[$ts] stopping KotakBotPaper NSSM to prevent re-spawn" | Out-File -FilePath $logFile -Append
& $nssm stop KotakBotPaper 2>&1 | Out-File -FilePath $logFile -Append
"[$ts] done" | Out-File -FilePath $logFile -Append
