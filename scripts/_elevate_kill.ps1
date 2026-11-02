# Kill the old operator process and restart the operator service with new code
$ErrorActionPreference = "Continue"
Write-Output "Killing old operator PID 7884"
Stop-Process -Id 7884 -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3
$alive = Get-Process -Id 7884 -ErrorAction SilentlyContinue
if ($alive) { Write-Output "PID 7884 STILL ALIVE" } else { Write-Output "PID 7884 killed" }
# Restart the operator service to ensure only ONE (new-code) operator runs
Write-Output "Restarting KotakOperator service"
Stop-Service KotakOperator -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3
Start-Service KotakOperator -ErrorAction SilentlyContinue
Write-Output "Done"
