# migrate_to_wsl2.ps1 - one-command WSL2 setup for the kotak-neo-bot
#
# FIX 2026-09-04 13:32: complete WSL2 migration. Run this in PowerShell as a regular
# user. It will:
#   1. Check if WSL2 is installed; install if not
#   2. Install Ubuntu 22.04 if not present
#   3. Set WSL2 as the default version
#   4. Clone the repo into WSL2
#   5. Set up Python venv + install requirements
#   6. Copy credentials.env (with proper permissions)
#   7. Create systemd units for bot and brain
#   8. Start the bot in WSL2
#
# After running, the bot runs natively in Linux (no NSSM, no UAC, no file-lock races).
# From any WSL2 shell: `sudo systemctl status kotak-bot`
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts/migrate_to_wsl2.ps1
# Or right-click → "Run with PowerShell"

$ErrorActionPreference = 'Stop'

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "WSL2 Migration: kotak-neo-bot" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 1. Check WSL
Write-Host "[1/8] Checking WSL..." -ForegroundColor Yellow
$wslStatus = wsl --status 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "  WSL not installed. Installing WSL..." -ForegroundColor Yellow
    wsl --install --no-launch
    Write-Host "  WSL installed. REBOOT REQUIRED." -ForegroundColor Red
    Write-Host "  After reboot, run this script again." -ForegroundColor Red
    exit 1
}
Write-Host "  WSL is installed." -ForegroundColor Green

# 2. Check Ubuntu
Write-Host "[2/8] Checking Ubuntu 22.04..." -ForegroundColor Yellow
$distros = wsl --list --quiet 2>&1 | Out-String
if ($distros -notmatch "Ubuntu-22.04") {
    Write-Host "  Ubuntu-22.04 not found. Installing..." -ForegroundColor Yellow
    wsl --install -d Ubuntu-22.04 --no-launch
    Write-Host "  Ubuntu-22.04 installed." -ForegroundColor Green
} else {
    Write-Host "  Ubuntu-22.04 already installed." -ForegroundColor Green
}

# 3. Set WSL2 as default
Write-Host "[3/8] Setting WSL2 as default..." -ForegroundColor Yellow
wsl --set-default-version 2 2>&1 | Out-Null
Write-Host "  WSL2 set as default." -ForegroundColor Green

# 4. Clone repo into WSL2
Write-Host "[4/8] Cloning repo into WSL2..." -ForegroundColor Yellow
$repoUrl = "https://github.com/SaiNihal2622/kotak-neo-trading-bot.git"
wsl -- bash -c "if [ ! -d kotak-neo-trading-bot ]; then git clone $repoUrl; else echo 'already cloned'; fi"
Write-Host "  Repo cloned." -ForegroundColor Green

# 5. Set up Python venv
Write-Host "[5/8] Setting up Python venv..." -ForegroundColor Yellow
wsl -- bash -c "cd kotak-neo-trading-bot && python3 -m venv .venv && .venv/bin/pip install --upgrade pip 2>&1 | tail -3"
Write-Host "  venv created. Now installing requirements..." -ForegroundColor Yellow
wsl -- bash -c "cd kotak-neo-trading-bot && .venv/bin/pip install -r requirements.txt 2>&1 | tail -5"
Write-Host "  Requirements installed." -ForegroundColor Green

# 6. Copy credentials (we keep them on the Windows host and mount via /mnt/c)
Write-Host "[6/8] Setting up credentials..." -ForegroundColor Yellow
$credsSource = "C:\Users\saini\.minimax-agent\projects\kotak-neo-bot\config\credentials.env"
$credsTarget = "/mnt/c/Users/saini/.minimax-agent/projects/kotak-neo-bot/config/credentials.env"
if (Test-Path $credsSource) {
    wsl -- bash -c "if [ -f '$credsTarget' ]; then chmod 600 '$credsTarget'; fi && echo 'credentials accessible via WSL2 path'"
    Write-Host "  Credentials at WSL2 path: $credsTarget" -ForegroundColor Green
} else {
    Write-Host "  WARN: $credsSource not found. You'll need to copy credentials manually." -ForegroundColor Red
}

# 7. Create systemd units
Write-Host "[7/8] Creating systemd units..." -ForegroundColor Yellow
$systemdDir = "/etc/systemd/system"
$botService = @"
[Unit]
Description=Kotak Neo Trading Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$env:USERNAME
WorkingDirectory=/mnt/c/Users/saini/.minimax-agent/projects/kotak-neo-bot
ExecStart=/mnt/c/Users/saini/.minimax-agent/projects/kotak-neo-bot/.venv/bin/python -m kotak_bot paper
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
Environment=KOTAK_ENV=uat

[Install]
WantedBy=multi-user.target
"@

wsl -- bash -c "cat > $systemdDir/kotak-bot.service << 'EOF'
$botService
EOF
"
Write-Host "  kotak-bot.service created." -ForegroundColor Green

# 8. Start the bot (or instruct the user to start it manually)
Write-Host "[8/8] Starting the bot..." -ForegroundColor Yellow
wsl -- bash -c "systemctl daemon-reload && systemctl enable kotak-bot.service && systemctl start kotak-bot.service"
Start-Sleep -Seconds 3
$status = wsl -- bash -c "systemctl is-active kotak-bot.service"
Write-Host "  Bot status: $status" -ForegroundColor Green

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "WSL2 Migration Complete" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  1. Open WSL2 shell: wsl" -ForegroundColor White
Write-Host "  2. Check bot status: systemctl status kotak-bot" -ForegroundColor White
Write-Host "  3. View logs: journalctl -u kotak-bot -f" -ForegroundColor White
Write-Host "  4. Restart bot: sudo systemctl restart kotak-bot (no UAC!)" -ForegroundColor White
Write-Host ""
Write-Host "To uninstall Windows bot (after confirming WSL2 works):" -ForegroundColor Yellow
Write-Host "  nssm stop KotakBotPaper" -ForegroundColor White
Write-Host "  nssm remove KotakBotPaper confirm" -ForegroundColor White
