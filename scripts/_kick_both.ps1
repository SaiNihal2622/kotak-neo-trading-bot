# _kick_both.ps1 - One-shot UAC restart for BOTH the bot and the brain.
# Loads the new aggressive 24/7 code with:
#   - loosened 1% -> 2% per-trade cap, 5% -> 8% per-position cap
#   - fixed 3rd occurrence of Order shadow-import trap (line 1283)
#   - new brain prompt with confluence rule and session drift rule
#   - mavis_trades.json with EXECUTE_PLAN, max_positions=5 (no longer BLOCK)
# Right-click -> "Run with PowerShell" -> "Yes" on UAC prompt.
$nssm = "C:\Tools\nssm\nssm-2.24\win64\nssm.exe"
Write-Host "Stopping KotakBotPaper..." -ForegroundColor Yellow
& $nssm stop KotakBotPaper
Start-Sleep -Seconds 4
Write-Host "Stopping KotakQuantService (brain)..." -ForegroundColor Yellow
& $nssm stop KotakQuantService
Start-Sleep -Seconds 4
Write-Host "Starting KotakBotPaper (will load commit e31dd3f with new code)..." -ForegroundColor Yellow
& $nssm start KotakBotPaper
Start-Sleep -Seconds 3
Write-Host "Starting KotakQuantService (will load new brain prompt)..." -ForegroundColor Yellow
& $nssm start KotakQuantService
Start-Sleep -Seconds 5
Write-Host "Done. Both services restarted with new code." -ForegroundColor Green
Write-Host "Expected after 30 min: bot fills trades, brain issues OPENs with confluence rule."
Write-Host "Press Enter to exit"
Read-Host
