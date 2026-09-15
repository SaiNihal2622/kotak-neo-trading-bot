$ErrorActionPreference = "SilentlyContinue"
$root = "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot"
$py = Join-Path $root ".venv\Scripts\python.exe"
$logDir = Join-Path $root "Logs"

# Kill bot + http_server (user-space procs started 05:44)
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match "kotak_bot paper|kotak_bot.http_server" -and $_.ParentProcessId -ne 0 } | ForEach-Object {
  Write-Host "killing PID $($_.ProcessId): $($_.CommandLine.Substring(0, 60))"
  Stop-Process -Id $_.ProcessId -Force
}
Start-Sleep -Seconds 2

# Start new bot
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $py
$psi.WorkingDirectory = $root
$psi.Arguments = "-u -m kotak_bot paper"
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $true
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$p = [System.Diagnostics.Process]::Start($psi)
Write-Host "started bot PID $($p.Id) (new code: write the file then start)"
Start-Sleep -Seconds 3

# Verify
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match "kotak_bot paper" } | ForEach-Object { Write-Host "bot: PID $($_.ProcessId) | started $($_.CreationDate.ToString('HH:mm:ss'))" }
$conn = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -eq 8502 }
if ($conn) { Write-Host "8502 listening PID $($conn.OwningProcess)" } else { Write-Host "8502 NOT listening" }
