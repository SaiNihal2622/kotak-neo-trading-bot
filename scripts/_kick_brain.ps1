# One-liner for the user to UAC-restart the brain with new aggressive 24/7 code.
# Right-click -> Run with PowerShell -> "Yes" to UAC prompt
# After this run, brain loads commit cad5c68 (label fix on top of bde1778 24/7 mode).
$nssm = "C:\Tools\nssm\nssm-2.24\win64\nssm.exe"
Write-Host "Stopping KotakQuantService (NSSM)..." -ForegroundColor Yellow
& $nssm stop KotakQuantService
Start-Sleep -Seconds 4
Write-Host "Starting KotakQuantService (will load commit cad5c68 with new code)..." -ForegroundColor Yellow
& $nssm start KotakQuantService
Start-Sleep -Seconds 5
Write-Host "Done. Brain should now be at LLM=0 with new code." -ForegroundColor Green
Write-Host "Expected after 30 min: LLM=2-4 (15-min periodic scan, 30-min overnight)"
Write-Host "Press Enter to exit"
Read-Host
