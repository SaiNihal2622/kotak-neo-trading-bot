# Jarvis/OpenClaw VPS - One-Click Deploy Script (Windows PowerShell)
# Run this on Windows to deploy to your VPS via SSH

# Requirements: Docker, Docker Compose, Git, SSH client

$ErrorActionPreference = "Stop"

$VPS_USER = "root"  # Change to your VPS username
$VPS_IP = "your-vps-ip-here"  # Change to your VPS IP
$VPS_PORT = 22
$PROJECT_NAME = "kotak-neo-trading-bot"
$GIT_REPO = "https://github.com/SaiNihal2622/kotak-neo-trading-bot.git"

Write-Host "==========================================" -ForegroundColor Green
Write-Host "  Jarvis/OpenClaw VPS Deployment" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green

# Check prerequisites
Write-Host "`n[1/6] Checking prerequisites..." -ForegroundColor Yellow

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "Docker not found. Please install Docker Desktop." -ForegroundColor Red
    exit 1
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "Git not found. Please install Git." -ForegroundColor Red
    exit 1
}

Write-Host "Prerequisites OK" -ForegroundColor Green

# Copy files to VPS
Write-Host "`n[2/6] Copying files to VPS..." -ForegroundColor Yellow

# Create remote directory
ssh -p $VPS_PORT $VPS_USER@$VPS_IP "mkdir -p /opt/jarvis/kotak-neo-bot"

# Copy project files (excluding .git, .venv, __pycache__)
rsync -avz -e "ssh -p $VPS_PORT" --exclude='.git' --exclude='.venv' --exclude='__pycache__' --exclude='data_cache' --exclude='Logs' --exclude='*.pyc' ./ $VPS_USER@$VPS_IP:/opt/jarvis/kotak-neo-bot/

Write-Host "Files copied to VPS" -ForegroundColor Green

# Deploy on VPS
Write-Host "`n[3/6] Deploying on VPS..." -ForegroundColor Yellow

ssh -p $VPS_PORT $VPS_USER@$VPS_IP << 'SSH_END'
cd /opt/jarvis/kotak-neo-bot

# Create .env if not exists
if [ ! -f jarvis/.env ]; then
    cp jarvis/.env.example jarvis/.env
    echo "WARNING: Please edit jarvis/.env with your credentials!"
fi

# Start services
cd jarvis
docker-compose down 2>/dev/null || true
docker-compose up -d --build

# Wait for services
sleep 30

# Verify
docker-compose ps

SSH_END

Write-Host "`n==========================================" -ForegroundColor Green
Write-Host "  Deployment Complete!" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Services:" -ForegroundColor Yellow
Write-Host "  Kotak Operator:    http://$VPS_IP:8510" -ForegroundColor Cyan
Write-Host "  Kronos Forecast:   http://$VPS_IP:8506" -ForegroundColor Cyan
Write-Host "  Crypto Options:    http://$VPS_IP:8511" -ForegroundColor Cyan
Write-Host "  Crypto Funded:     http://$VPS_IP:8512" -ForegroundColor Cyan
Write-Host "  Forex Funded:      http://$VPS_IP:8513" -ForegroundColor Cyan
Write-Host "  Jarvis AI:         http://$VPS_IP:8080" -ForegroundColor Cyan
Write-Host "  Adziga Agency:     http://$VPS_IP:8090" -ForegroundColor Cyan
Write-Host ""
Write-Host "Jarvis UI: http://$VPS_IP:8080/jarvis" -ForegroundColor Yellow
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "  1. Edit jarvis/.env on the VPS with your API credentials"
Write-Host "  2. Run: docker-compose up -d"
Write-Host "  3. Access Jarvis UI at http://$VPS_IP:8080/jarvis"