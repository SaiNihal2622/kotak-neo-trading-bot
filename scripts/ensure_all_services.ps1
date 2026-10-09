# Ensure all Kotak core services are RUNNING. Start any that are not.
# Designed to run at boot (scheduled task) and periodically (watchdog).
# NSSM services auto-restart on crash, but NOT on a hung state -- this
# catches the hung case and the post-reboot case.
$nssm = 'C:\Tools\nssm\nssm-2.24\win64\nssm.exe'
$log  = 'C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\data_cache\service_ensure.log'
$core = @('KotakBotPaper','KotakQuantService','KotakCoreAPI','KotakExecGateway','KotakDashboard','KotakBrainBridge')

function Log($msg) {
    $line = "[$(Get-Date -Format 'yyyy-MM-ddTHH:mm:ss')] $msg"
    Add-Content -Path $log -Value $line
    Write-Output $line
}

Add-Content -Path $log -Value "----- ensure run -----"
$changed = $false
foreach ($svc in $core) {
    $state = (sc.exe query $svc 2>$null | Select-String 'STATE' | ForEach-Object { ($_ -split ':')[1].Trim() })
    if ($state -match 'RUNNING') {
        Log "OK $svc running"
    } elseif ($state -match 'PAUSED') {
        Log "resume $svc (paused)"
        & $nssm continue-service $svc
        $changed = $true
    } else {
        Log "start $svc (state=$state)"
        & $nssm start $svc
        $changed = $true
    }
    Start-Sleep -Milliseconds 400
}

# Verify
$all_ok = $true
foreach ($svc in $core) {
    $state = (sc.exe query $svc 2>$null | Select-String 'STATE' | ForEach-Object { ($_ -split ':')[1].Trim() })
    if ($state -notmatch 'RUNNING') { $all_ok = $false; Log "FAIL $svc = $state" }
}
if ($all_ok) { Log "ALL CORE SERVICES RUNNING" } else { Log "SOME SERVICES NOT RUNNING - check above" }
