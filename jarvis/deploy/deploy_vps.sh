# Jarvis/OpenClaw VPS Deployment Script
# Run this on your Ubuntu VPS to deploy the complete trading system
#!/bin/bash

set -e

echo "=========================================="
echo "  Jarvis/OpenClaw VPS Deployment"
echo "  Complete Autonomous Trading System"
echo "=========================================="

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}Step 1: Updating system packages...${NC}"
sudo apt-get update -y
sudo apt-get upgrade -y

echo -e "${GREEN}Step 2: Installing Docker...${NC}"
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    sudo usermod -aG docker $USER
    newgrp docker
else
    echo "Docker already installed"
fi

echo -e "${GREEN}Step 3: Installing Docker Compose...${NC}"
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    sudo apt-get install -y docker-compose-plugin
fi

echo -e "${GREEN}Step 4: Creating project directory...${NC}"
sudo mkdir -p /opt/jarvis
sudo chown $USER:$USER /opt/jarvis
cd /opt/jarvis

echo -e "${GREEN}Step 5: Cloning repository...${NC}"
if [ ! -d "kotak-neo-bot" ]; then
    git clone https://github.com/SaiNihal2622/kotak-neo-trading-bot.git
fi
cd kotak-neo-bot

echo -e "${GREEN}Step 6: Setting up environment...${NC}"
if [ ! -f jarvis/.env ]; then
    cp jarvis/.env.example jarvis/.env
    echo -e "${YELLOW}WARNING: Please edit jarvis/.env with your actual credentials!${NC}"
fi

echo -e "${GREEN}Step 7: Starting all services...${NC}"
cd jarvis
docker-compose up -d --build

echo -e "${GREEN}Step 8: Waiting for services to start...${NC}"
sleep 30

echo -e "${GREEN}Step 9: Verifying services...${NC}"
docker-compose ps

echo -e "${GREEN}
==========================================
  Jarvis Deployment Complete!
==========================================
Services:
  - Kotak Operator:    http://your-vps-ip:8510
  - Kronos Forecast:   http://your-vps-ip:8506
  - Crypto Options:    http://your-vps-ip:8511
  - Crypto Funded:     http://your-vps-ip:8512
  - Forex Funded:      http://your-vps-ip:8513
  - Jarvis AI:         http://your-vps-ip:8080
  - Adziga Agency:     http://your-vps-ip:8090

Jarvis UI: http://your-vps-ip:8080/jarvis

Next steps:
1. Edit jarvis/.env with your API credentials
2. Edit jarvis/docker-compose.yml if needed
3. Run: docker-compose up -d
4. Access Jarvis UI at http://your-vps-ip:8080/jarvis
==========================================
${NC}"