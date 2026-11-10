# Jarvis/OpenClaw - VPS Deployment Guide
# Complete setup for 24/7 autonomous trading

# ============================================
# PREREQUISITES
# ============================================
# 1. VPS with Ubuntu 22.04+ (Oracle Cloud Always Free recommended)
# 2. Docker & Docker Compose installed
# 3. Git installed
# 4. Domain name (optional, for SSL)
# 5. Credit/Debit card for VPS signup verification

# ============================================
# STEP 1: CREATE VPS
# ============================================
# Option A: Oracle Cloud Always Free (RECOMMENDED - $0 forever)
# - 2 Arm OCPU / 12 GB RAM / 200 GB disk
# - Always free, no expiry
# - Sign up: https://www.oracle.com/cloud/free/
#
# Option B: Google Cloud e2-micro (Always Free, $0)
# - 2 vCPU / 1 GB RAM / 30 GB disk
# - Only in US regions (Oregon, Iowa, South Carolina)
# - Sign up: https://cloud.google.com/free
#
# Option C: Hetzner Cloud (Paid, ~€5/month)
# - 2 vCPU / 4 GB RAM / 40 GB disk
# - More reliable than free tiers
# - Sign up: https://www.hetzner.com/cloud

# ============================================
# STEP 2: CONNECT TO VPS
# ============================================
ssh -p 22 your_username@your_vps_ip

# ============================================
# STEP 3: RUN DEPLOYMENT
# ============================================
cd /opt/jarvis/kotak-neo-bot/jarvis
chmod +x deploy_vps.sh
./deploy_vps.sh

# ============================================
# STEP 4: CONFIGURE CREDENTIALS
# ============================================
# Edit jarvis/.env with your actual API keys
nano jarvis/.env

# Required credentials:
# - KOTAK_API_KEY, KOTAK_API_SECRET, KOTAK_UCC, KOTAK_TOTP_SECRET, KOTAK_MPIN
# - DERIBIT_CLIENT_ID, DERIBIT_CLIENT_SECRET (for crypto options)
# - FOREX_API_KEY, FOREX_API_SECRET (for forex funded)
# - JARVIS_API_KEY (for Jarvis AI assistant)
# - ADZIGA_INSTAGRAM_USERNAME, ADZIGA_INSTAGRAM_PASSWORD (for ad agency)

# ============================================
# STEP 5: START SERVICES
# ============================================
cd jarvis
docker-compose up -d --build

# Wait for services to start (about 2-3 minutes)
sleep 30

# Verify all services are running
docker-compose ps

# ============================================
# STEP 6: ACCESS JARVIS
# ============================================
# Open your browser and go to:
# http://your-vps-ip:8080/jarvis

# You can now control the entire trading system from:
# - Your laptop browser
# - Your phone browser (Hermes app or any browser)
# - Any device with internet access

# ============================================
# STEP 7: MONITOR & MANAGE
# ============================================
# View logs:
docker-compose logs -f

# Restart a service:
docker-compose restart kotak-operator

# Stop all services:
docker-compose down

# Start all services:
docker-compose up -d

# View real-time logs:
docker-compose logs -f kotak-operator

# ============================================
# ARCHITECTURE OVERVIEW
# ============================================
# 
# ┌─────────────────────────────────────────────────────────────┐
# │                    JARVIS / OPENCLAW                         │
# │                    VPS DEPLOYMENT                            │
# ├─────────────────────────────────────────────────────────────┤
# │                                                              │
# │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
# │  │  Kotak      │  │  Kronos     │  │  Crypto     │         │
# │  │  Operator   │  │  Forecast   │  │  Options    │         │
# │  │  (NSE)      │  │  (AI/ML)    │  │  (Deribit)  │         │
# │  └─────────────┘  └─────────────┘  └─────────────┘         │
# │                                                              │
# │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
# │  │  Crypto     │  │  Forex      │  │  Jarvis AI  │         │
# │  │  Funded     │  │  Funded     │  │  (UI+API)   │         │
# │  │  Bot        │  │  Bot        │  │               │         │
# │  └─────────────┘  └─────────────┘  └─────────────┘         │
# │                                                              │
# │  ┌─────────────┐                                            │
# │  │  Adziga     │                                            │
# │  │  Agency     │                                            │
# │  │  (Sweet     │                                            │
# │  │  Desire)    │                                            │
# │  └─────────────┘                                            │
# │                                                              │
# │  ┌─────────────┐  ┌─────────────┐                          │
# │  │  Redis      │  │  PostgreSQL │                          │
# │  │  (Cache)    │  │  (DB)       │                          │
# │  └─────────────┘  └─────────────┘                          │
# └─────────────────────────────────────────────────────────────┘

# ============================================
# SECURITY NOTES
# ============================================
# 1. Never commit .env with real credentials to git
# 2. Use strong passwords for PostgreSQL
# 3. Enable UFW firewall: ufw allow 22, ufw allow 8080, etc.
# 4. Consider using Docker secrets for production
# 5. Set up automatic backups of /opt/jarvis/kotak-neo-bot/data
# 6. Monitor logs: docker-compose logs -f

# ============================================
# TROUBLESHOOTING
# ============================================
# Container won't start: docker-compose logs <service-name>
# Can't access port: Check VPS firewall/security group
# Container crashes: Check docker-compose logs
# Database issues: docker-compose exec postgres psql -U jarvis -d jarvis_trading

# ============================================
# CONTACT & SUPPORT
# ============================================
# For issues with the trading system, check:
# 1. docker-compose logs -f
# 2. Jarvis UI: http://your-vps-ip:8080/jarvis
# 3. Individual service health: http://your-vps-ip:PORT/health