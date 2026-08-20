# =============================================================================
# uninstall_service.ps1 — Stop and remove KotakBotPaper + KotakDashboard services.
# Run as Administrator.
# =============================================================================
$ErrorActionPreference = 'Stop'
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  Write-Host "ERROR: Run as Administrator" -ForegroundColor Red
  exit 1
}

$NssmExe = 'C:\Tools\nssm\nssm-2.24\win64\nssm.exe'

foreach ($name in 'KotakBotPaper', 'KotakDashboard') {
  Write-Host "Removing: $name" -ForegroundColor Cyan
  & $NssmExe stop $name 2>$null
  Start-Sleep -Seconds 2
  & $NssmExe remove $name confirm
}
Write-Host "Done." -ForegroundColor Green
