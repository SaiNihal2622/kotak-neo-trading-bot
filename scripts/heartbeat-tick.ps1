$ErrorActionPreference = 'Stop'
$procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'kotak_bot' -and $_.CommandLine -notmatch 'powershell' } | Select-Object ProcessId, @{N='uptime_min';E={[math]::Round(((Get-Date) - $_.CreationDate).TotalMinutes,1)}}, @{N='cmd';E={ if ($_.CommandLine.Length -gt 80) { $_.CommandLine.Substring(0,80) } else { $_.CommandLine } }}
$dash = Test-NetConnection 127.0.0.1 -Port 8501 -InformationLevel Quiet
$log = Get-Item 'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\bot_stderr.log' -ErrorAction SilentlyContinue
$age = if ($log) { [math]::Round(((Get-Date) - $log.LastWriteTime).TotalMinutes,1) } else { 'NA' }
Write-Output "BOT_PROCS_COUNT=$(($procs|Measure-Object).Count)"
foreach ($p in $procs) {
  Write-Output "  PID=$($p.ProcessId) UP=$($p.uptime_min)m CMD=$($p.cmd)"
}
Write-Output "DASH_8501=$dash"
Write-Output "ACTIVE_LOG_AGE_MIN=$age"
Write-Output "NOW_IST=$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
