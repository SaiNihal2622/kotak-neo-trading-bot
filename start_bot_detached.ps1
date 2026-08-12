# Start kotak_bot in paper+live_kotak mode, fully detached from this shell.
# Survives the 30-min PowerShell task cap. Logs to logs\bot.log.

$ErrorActionPreference = 'Stop'
$project = 'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot'
Set-Location $project

# Source env vars from credentials.env
$envFile = Join-Path $project 'config\credentials.env'
Get-Content $envFile -Encoding UTF8 | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith('#') -and $line -match '^([^=]+)=(.*)$') {
        [Environment]::SetEnvironmentVariable($matches[1], $matches[2], 'Process')
    }
}
# Force live_kotak to use PROD endpoint + 3s poll (overrides credentials.env defaults)
$env:KOTAK_ENV = 'prod'
$env:KOTAK_PROD_POLL_SEC = '3'
$env:PYTHONUNBUFFERED = '1'

# Kill any existing kotak_bot paper process
$existing = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'kotak_bot' }
foreach ($p in $existing) {
    Write-Host "Killing existing bot PID $($p.ProcessId)"
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 2

# Launch detached
$logFile = Join-Path $project 'logs\bot.log'
$errFile = Join-Path $project 'logs\bot_stderr.log'
$exe     = Join-Path $project '.venv\Scripts\python.exe'

Write-Host "Starting kotak_bot paper (live_kotak mode) detached..."
Write-Host "  exe:   $exe"
Write-Host "  log:   $logFile"
Write-Host "  err:   $errFile"
Write-Host "  env:   KOTAK_ENV=$($env:KOTAK_ENV)  KOTAK_PROD_POLL_SEC=$($env:KOTAK_PROD_POLL_SEC)"

$proc = Start-Process -FilePath $exe `
    -ArgumentList '-u', '-m', 'kotak_bot', 'paper' `
    -WorkingDirectory $project `
    -RedirectStandardOutput $logFile `
    -RedirectStandardError  $errFile `
    -WindowStyle Hidden `
    -PassThru

Write-Host ""
Write-Host "Bot started: PID $($proc.Id)  (detached, will survive this shell exiting)"
Start-Sleep -Seconds 5
Get-Process -Id $proc.Id -ErrorAction SilentlyContinue |
    Select-Object Id, ProcessName, StartTime, @{N='uptime_sec';E={[math]::Round(((Get-Date) - $_.StartTime).TotalSeconds,1)}} |
    Format-Table -AutoSize
