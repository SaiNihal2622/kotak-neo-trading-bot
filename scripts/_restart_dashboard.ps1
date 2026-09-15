$ErrorActionPreference = "SilentlyContinue"
$root = "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot"
$py = Join-Path $root ".venv\Scripts\python.exe"
$logDir = Join-Path $root "Logs"

# Kill old
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'live_dashboard' } | ForEach-Object {
  Write-Host "killing PID $($_.ProcessId)"
  Stop-Process -Id $_.ProcessId -Force
}
Start-Sleep -Seconds 2

# Start new
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $py
$psi.WorkingDirectory = $root
$psi.Arguments = "-u scripts\live_dashboard.py"
$psi.UseShellExecute = $false
$psi.CreateNoWindow = $true
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$p = [System.Diagnostics.Process]::Start($psi)
Write-Host "started PID $($p.Id)"
Start-Sleep -Seconds 3

# Verify
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'live_dashboard' } | ForEach-Object { Write-Host "live_dashboard PID $($_.ProcessId)" }
$conn = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -eq 8504 }
if ($conn) { Write-Host "8504 listening PID $($conn.OwningProcess)" } else { Write-Host "8504 NOT listening" }
