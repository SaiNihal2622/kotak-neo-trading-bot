# Full bot cleanup + NSSM takeover — one shot, no orphans.
$ErrorActionPreference = "SilentlyContinue"
$root = "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot"
$nssm = "C:\Tools\nssm\nssm-2.24\win64\nssm.exe"
$logFile = "$root\Logs\_orphan_kill.log"
$ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

function logm($msg) { "[$ts] $msg" | Out-File -FilePath $logFile -Append; Write-Host $msg }

logm "=== FULL BOT CLEANUP + NSSM TAKEOVER ==="

# 1. Stop KotakBotPaper NSSM (so it doesn't respawn)
logm "1. stopping KotakBotPaper NSSM service"
& $nssm stop KotakBotPaper 2>&1 | Out-File -FilePath $logFile -Append
Start-Sleep -Seconds 2

# 2. Kill ALL python processes whose command line mentions kotak_bot paper or http_server
logm "2. killing ALL kotak_bot python procs (both user-space and NSSM children)"
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -match "kotak_bot" } |
  ForEach-Object {
    $pid_kill = $_.ProcessId
    logm "   -> taskkill /F /T /PID $pid_kill"
    cmd /c "taskkill /F /T /PID $pid_kill" 2>&1 | Out-File -FilePath $logFile -Append
  }

# 3. Kill ALL watchdog processes (powershell with watchdog.ps1 in cmdline)
logm "3. killing ALL watchdog processes"
Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
  Where-Object { $_.CommandLine -match "watchdog" } |
  ForEach-Object {
    $pid_kill = $_.ProcessId
    logm "   -> taskkill /F /T /PID $pid_kill (powershell watchdog)"
    cmd /c "taskkill /F /T /PID $pid_kill" 2>&1 | Out-File -FilePath $logFile -Append
  }

# 4. Kill any user-space bot launchers (powershell with -m kotak_bot in cmdline)
logm "4. killing any user-space kotak_bot launchers"
Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
  Where-Object { $_.CommandLine -match "kotak_bot paper" } |
  ForEach-Object {
    $pid_kill = $_.ProcessId
    logm "   -> taskkill /F /T /PID $pid_kill (powershell launcher)"
    cmd /c "taskkill /F /T /PID $pid_kill" 2>&1 | Out-File -FilePath $logFile -Append
  }

Start-Sleep -Seconds 3

# 5. Verify only NSSM-orphans remain (we'll remove them by stopping their parent service)
logm "5. python procs remaining (orphans we couldn't kill with our perms):"
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -eq "" -and $_.ParentProcessId -ne 0 } |
  ForEach-Object { logm "   empty-cmd PID $($_.ProcessId) parent=$($_.ParentProcessId) started $($_.CreationDate.ToString('HH:mm:ss'))" }

# 6. Disable watchdog.ps1 by renaming (so user-logon restart doesn't fire it)
$wd = "$root\watchdog.ps1"
$wdDisabled = "$root\watchdog.ps1.disabled"
if (Test-Path $wd) {
  Move-Item -Path $wd -Destination $wdDisabled -Force
  logm "6. disabled watchdog.ps1 -> watchdog.ps1.disabled"
} else {
  logm "6. watchdog.ps1 already disabled"
}

# 7. Start KotakBotPaper NSSM (it owns the bot via run_bot.ps1)
logm "7. starting KotakBotPaper NSSM (will own the bot + http_server)"
& $nssm start KotakBotPaper 2>&1 | Out-File -FilePath $logFile -Append
Start-Sleep -Seconds 6

# 8. Verify single NSSM-owned bot
logm "8. final state — python procs (should be ONE kotak_bot paper set):"
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -match "kotak_bot" } |
  ForEach-Object { logm "   PID $($_.ProcessId) parent=$($_.ParentProcessId) started $($_.CreationDate.ToString('HH:mm:ss')) | $((Get-Date) - $_.CreationDate).TotalMinutes.ToString('0.0')m old | cmd=$($_.CommandLine.Substring(0, 80))" }

# 9. Check :8502
$conn = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -eq 8502 }
if ($conn) {
  logm "9. :8502 listening PID $($conn.OwningProcess) ✓"
} else {
  logm "9. :8502 NOT listening — http_server not started yet, will start when NSSM bot launches it"
}

logm "=== done ==="
