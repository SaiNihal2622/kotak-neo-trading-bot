$ErrorActionPreference = "SilentlyContinue"
$logFile = "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\Logs\_orphan_kill.log"
$ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

# Kill the watchdog-spawned bot (PIDs 18344 + 18240) and disable the watchdog so
# it doesn't keep spawning duplicates. NSSM KotakBotPaper is now the SOLE bot owner.
"[$ts] killing watchdog-spawned bot 18344 + 18240" | Out-File -FilePath $logFile -Append
foreach ($pid_kill in @(18344, 18240)) {
  $p = Get-CimInstance Win32_Process -Filter "ProcessId = $pid_kill" -ErrorAction SilentlyContinue
  if ($p) {
    cmd /c "taskkill /F /T /PID $pid_kill" 2>&1 | Out-File -FilePath $logFile -Append
  }
}
Start-Sleep -Seconds 2

# Disable watchdog by renaming it (so it doesn't fire on next logon)
$wd = "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\watchdog.ps1"
$wdDisabled = "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\watchdog.ps1.disabled"
if (Test-Path $wd) {
  Move-Item -Path $wd -Destination $wdDisabled -Force
  "  disabled watchdog.ps1 -> watchdog.ps1.disabled" | Out-File -FilePath $logFile -Append
}

# Also kill the watchdog process so it stops looping
foreach ($p in (Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" | Where-Object { $_.CommandLine -match 'watchdog' })) {
  cmd /c "taskkill /F /T /PID $($p.ProcessId)" 2>&1 | Out-File -FilePath $logFile -Append
}

"[$ts] done" | Out-File -FilePath $logFile -Append
