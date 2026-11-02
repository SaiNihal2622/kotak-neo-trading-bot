# Restore Kotak trading NSSM services that are paused or stopped.
# Run as Administrator (this script checks and self-notes if not elevated).
$nssm = 'C:\Tools\nssm\nssm-2.24\win64\nssm.exe'
$log = 'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\service_restore.log'

function Log($msg) {
    $line = "[$(Get-Date -Format 'yyyy-MM-ddTHH:mm:ss')] $msg"
    Add-Content -Path $log -Value $line
    Write-Output $line
}

$now = Get-Date
Add-Content -Path $log -Value "----- service restore run -----"

foreach ($svc in @('KotakBrainDaemon', 'KotakMavisRealtime', 'KotakHttpServer')) {
    $state = (sc.exe query $svc 2>$null | Select-String 'STATE' | ForEach-Object { ($_ -split ':')[1].Trim() })
    Log "checking $svc state=$state"
    if ($state -match 'PAUSED') {
        Log "resuming $svc (paused -> running)"
        & $nssm continue-service $svc
    } elseif ($state -match 'STOPPED' -or -not $state) {
        Log "starting $svc (stopped -> running)"
        & $nssm start $svc
    } else {
        Log "$svc already running"
    }
    Start-Sleep -Milliseconds 500
}

# Verify final states
foreach ($svc in @('KotakBrainDaemon', 'KotakMavisRealtime', 'KotakHttpServer')) {
    $state = (sc.exe query $svc 2>$null | Select-String 'STATE' | ForEach-Object { ($_ -split ':')[1].Trim() })
    Log "final $svc = $state"
}
Log "done"
