$ErrorActionPreference = 'Stop'
Set-Location 'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot'
$alive = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*kotak-neo-bot*' -and $_.StartTime -gt (Get-Date).AddHours(-4) } | Measure-Object | Select-Object -ExpandProperty Count
$alive2 = Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*kotak-neo-bot*' } | Measure-Object | Select-Object -ExpandProperty Count
$dash = try { (Invoke-WebRequest -Uri 'http://localhost:8501/_stcore/health' -UseBasicParsing -TimeoutSec 5).StatusCode } catch { 'DOWN' }
$errs = Select-String -Path 'bot_stderr.log' -Pattern 'Traceback|FATAL|Killed|Exception' -ErrorAction SilentlyContinue | Select-Object -Last 3
$hour = (Get-Date).Hour
$min = (Get-Date).Minute
$dow = (Get-Date).DayOfWeek
$mktHours = ((($hour -gt 9) -or ($hour -eq 9)) -and (($hour -lt 15) -or ($hour -eq 15 -and $min -le 30))) -and ($dow -ne 'Saturday') -and ($dow -ne 'Sunday')
Write-Host "alive4h=$alive aliveTotal=$alive2 dash=$dash mktHours=$mktHours"
if ($errs) { Write-Host '---errs---'; $errs | ForEach-Object { Write-Host $_.Line } }
