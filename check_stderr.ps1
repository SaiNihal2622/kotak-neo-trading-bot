$ErrorActionPreference = 'Stop'
$log = 'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\bot_stderr.log'
$info = Get-Item $log
Write-Host "LastWriteTime: $($info.LastWriteTime)"
Write-Host "Size: $($info.Length) bytes"
Write-Host "---"
$matches = Select-String -Path $log -Pattern 'Traceback|FATAL|Killed|Exception' | Select-Object -Last 5
foreach ($m in $matches) {
    Write-Host ("--- line {0}:" -f $m.LineNumber)
    Write-Host $m.Line
}
