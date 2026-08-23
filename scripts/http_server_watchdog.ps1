$ErrorActionPreference = 'Stop'
Set-Location "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot"
$env:PYTHONIOENCODING = "utf-8"
& ".\.venv\Scripts\python.exe" "scripts\http_server_watchdog.py" --port 8502
exit $LASTEXITCODE
