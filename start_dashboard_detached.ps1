# Start streamlit dashboard fully detached from this shell (survives 30-min cap).
$ErrorActionPreference = 'Stop'
$project = 'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot'
Set-Location $project

$env:PYTHONUNBUFFERED = '1'

# Kill any existing streamlit process for this project
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'streamlit' -and $_.CommandLine -match 'dashboard' } |
    ForEach-Object {
        Write-Host "Killing existing dashboard PID $($_.ProcessId)"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
Start-Sleep -Seconds 2

$logFile = Join-Path $project 'logs\dashboard.log'
$exe     = Join-Path $project '.venv\Scripts\python.exe'

Write-Host "Starting dashboard detached..."
$proc = Start-Process -FilePath $exe `
    -ArgumentList '-u', '-m', 'streamlit', 'run', 'dashboard\app.py', '--server.port=8501', '--server.headless=true' `
    -WorkingDirectory $project `
    -RedirectStandardOutput $logFile `
    -WindowStyle Hidden `
    -PassThru

Write-Host "Dashboard started: PID $($proc.Id) (detached)"
Start-Sleep -Seconds 5
Get-Process -Id $proc.Id -ErrorAction SilentlyContinue |
    Select-Object Id, StartTime |
    Format-Table -AutoSize
