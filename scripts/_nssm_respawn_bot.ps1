$ErrorActionPreference = "SilentlyContinue"
$root = "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot"
$logFile = "$root\Logs\_orphan_kill.log"
$ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
function logm($msg) { "[$ts] $msg" | Out-File -FilePath $logFile -Append; Write-Host $msg }

logm "=== NSSM RESPAWN BOT (force pick up new code) ==="
# Kill the user-space bot (parent 13780) so NSSM respawns with new code
foreach ($pid_kill in @(4424, 1732)) {
  $p = Get-CimInstance Win32_Process -Filter "ProcessId = $pid_kill" -ErrorAction SilentlyContinue
  if ($p) {
    logm "  killing PID $pid_kill (cmd=$($p.CommandLine.Substring(0, [Math]::Min(60, $p.CommandLine.Length)))"
    cmd /c "taskkill /F /T /PID $pid_kill" 2>&1 | Out-File -FilePath $logFile -Append
  }
}
Start-Sleep -Seconds 3

# Verify NSSM is still running
$nssmStatus = & "C:\Tools\nssm\nssm-2.24\win64\nssm.exe" status KotakBotPaper 2>&1
logm "  nssm status: $nssmStatus"

# If NSSM is still running but bot process is dead, NSSM should respawn it automatically
# Wait up to 30s for respawn
for ($i = 0; $i -lt 6; $i++) {
  $bot = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'kotak_bot paper' -and $_.CommandLine -ne '' }
  if ($bot) {
    logm "  bot respawned: PID $($bot.ProcessId)"
    break
  } else {
    logm "  waiting for NSSM respawn ($i of 6)..."
    Start-Sleep -Seconds 5
  }
}

# Check :8502 status
$conn = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -eq 8502 }
if ($conn) {
  logm "  :8502 listening PID $($conn.OwningProcess)"
} else {
  logm "  :8502 NOT listening yet"
}

# Now start the http_server manually (NSSM doesn't auto-spawn it)
$py = ".\.venv\Scripts\python.exe"
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $py
$psi.WorkingDirectory = (Get-Location).Path
$psi.Arguments = "-u -m kotak_bot.http_server --port 8502"
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $true
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
[void][System.Diagnostics.Process]::Start($psi)
Start-Sleep -Seconds 3

$conn = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -eq 8502 }
if ($conn) {
  logm "  :8502 re-listening (PID $($conn.OwningProcess))"
}

logm "=== done ==="
