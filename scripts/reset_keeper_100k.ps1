$ErrorActionPreference = 'SilentlyContinue'
Set-Location 'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot'
$env:PYTHONPATH = 'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot'
$log = 'logs\reset_keeper_100k.log'
$ts0 = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
"START cap=100000  pid=$PID  ts=$ts0" | Out-File $log -Append
$i = 0
while ($true) {
  $i++
  $ts = Get-Date -Format 'HH:mm:ss'
  & .\.venv\Scripts\python.exe scripts\reset_paper.py --capital 100000 --no-backup *> $null
  $code = $LASTEXITCODE
  "$ts iter=$i exit=$code" | Out-File $log -Append
  Start-Sleep -Seconds 2
}
