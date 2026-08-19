$logPath = 'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\bot_stderr.log'
if (Test-Path $logPath) {
    $info = Get-Item $logPath
    $age = [math]::Round(((Get-Date) - $info.LastWriteTime).TotalMinutes, 1)
    Write-Host ("ROOT_LOG size={0} age={1}m lastWrite={2}" -f $info.Length, $age, $info.LastWriteTime)
    Get-Content $logPath -Tail 3 | ForEach-Object { Write-Host $_ }
} else {
    Write-Host 'ROOT_LOG_MISSING'
}
