# Auto-start live_dashboard on logon
$ErrorActionPreference = 'SilentlyContinue'
Set-Location "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot"
# Kill any existing instance
Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*kotak-neo-bot*' -and $_.CommandLine -like '*live_dashboard*' } | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1
# Start fresh
Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "-u", "scripts\live_dashboard.py" -WorkingDirectory "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot" -WindowStyle Hidden -RedirectStandardOutput "logs\live_dashboard.out" -RedirectStandardError "logs\live_dashboard.err"
Write-Output "live_dashboard started on http://localhost:8504/ (PID $(Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like '*live_dashboard*' } | Select-Object -First 1).Id))"