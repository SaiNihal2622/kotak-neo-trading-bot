#!/usr/bin/env bash
# setup_hetzner.sh - one-command Hetzner Cloud setup for kotak-neo-bot
#
# Run this on a fresh Hetzner CX11 (Ubuntu 22.04) to deploy the trading bot.
# After it runs, the bot will be:
#   - Running as systemd service (auto-restart on crash, no UAC needed)
#   - Connected to Kotak Neo (TOTP+MPIN)
#   - Sending Telegram alerts (configure your bot token)
#   - Logging to journald (rotated automatically)
#
# Usage (on the Hetzner server):
#   curl -sSL https://raw.githubusercontent.com/SaiNihal2622/kotak-neo-trading-bot/main/infra/setup_hetzner.sh | bash
# Or locally:
#   scp setup_hetzner.sh root@your-server:/root/
#   ssh root@your-server
#   bash /root/setup_hetzner.sh

set -euo pipefail

echo "=========================================="
echo "Hetzner Cloud setup: kotak-neo-bot"
echo "=========================================="

# 1. Update system
echo "[1/8] Updating system packages..."
apt update && apt upgrade -y

# 2. Install Python 3.12, git, sqlite3, etc.
echo "[2/8] Installing Python 3.12 + dependencies..."
apt install -y python3.12 python3.12-venv python3-pip git sqlite3 curl jq

# 3. Create 'kotak' user (don't run as root)
echo "[3/8] Creating kotak user..."
if ! id -u kotak >/dev/null 2>&1; then
    useradd -m -s /bin/bash kotak
    echo "  created user 'kotak'"
fi

# 4. Clone the repo
echo "[4/8] Cloning the bot repository..."
if [ ! -d /opt/kotak-neo-bot ]; then
    sudo -u kotak git clone https://github.com/SaiNihal2622/kotak-neo-trading-bot.git /opt/kotak-neo-bot
    echo "  cloned to /opt/kotak-neo-bot"
fi

# 5. Set up Python venv + install requirements
echo "[5/8] Setting up Python venv..."
sudo -u kotak python3.12 -m venv /opt/kotak-neo-bot/.venv
sudo -u kotak /opt/kotak-neo-bot/.venv/bin/pip install --upgrade pip
sudo -u kotak /opt/kotak-neo-bot/.venv/bin/pip install -r /opt/kotak-neo-bot/requirements.txt
echo "  venv ready at /opt/kotak-neo-bot/.venv"

# 6. Copy credentials (or set up)
echo "[6/8] Setting up credentials..."
mkdir -p /opt/kotak-neo-bot/config
if [ ! -f /opt/kotak-neo-bot/config/credentials.env ]; then
    echo "  /opt/kotak-neo-bot/config/credentials.env missing"
    echo "  Please create it with the following format (use chmod 600):"
    cat <<'EOF'
KOTAK_API_KEY=your_api_key_here
KOTAK_MOBILE=+91xxxxxxxxxx
KOTAK_UCC=your_ucc_here
KOTAK_TOTP_SECRET=your_totp_secret
KOTAK_MPIN=your_mpin_here
KOTAK_ENV=uat
KOTAK_LIVE_CONFIRMED=NO
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_telegram_chat_id
MINIMAX_LLM_API_KEY=your_minimax_api_key
EOF
    echo
    echo "  After creating, run: chmod 600 /opt/kotak-neo-bot/config/credentials.env"
    echo "  Then re-run this script."
    exit 1
fi
chmod 600 /opt/kotak-neo-bot/config/credentials.env
chown kotak:kotak /opt/kotak-neo-bot/config/credentials.env
echo "  credentials secured (chmod 600)"

# 7. Create systemd units
echo "[7/8] Creating systemd units..."
cat > /etc/systemd/system/kotak-bot.service <<'EOF'
[Unit]
Description=Kotak Neo Trading Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=kotak
WorkingDirectory=/opt/kotak-neo-bot
ExecStart=/opt/kotak-neo-bot/.venv/bin/python -m kotak_bot paper
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
EnvironmentFile=/opt/kotak-neo-bot/config/credentials.env
Environment=KOTAK_ENV=uat

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/kotak-brain.service <<'EOF'
[Unit]
Description=Kotak Quant Brain (LLM)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=kotak
WorkingDirectory=/opt/kotak-neo-bot
ExecStart=/opt/kotak-neo-bot/.venv/bin/python -u scripts/quant_service.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
EnvironmentFile=/opt/kotak-neo-bot/config/credentials.env

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable kotak-bot.service kotak-brain.service
systemctl start kotak-bot.service kotak-brain.service
echo "  systemd units created and started"

# 8. Verify
echo "[8/8] Verifying..."
sleep 5
echo "  Bot status: $(systemctl is-active kotak-bot.service)"
echo "  Brain status: $(systemctl is-active kotak-brain.service)"
echo
echo "=========================================="
echo "Hetzner Cloud setup complete!"
echo "=========================================="
echo
echo "Useful commands:"
echo "  systemctl status kotak-bot    # check bot status"
echo "  journalctl -u kotak-bot -f     # view bot logs"
echo "  systemctl restart kotak-bot    # restart bot (no UAC needed!)"
echo "  systemctl stop kotak-bot       # stop bot"
echo
echo "Telegram commands (after starting):"
echo "  /health     - liveness summary"
echo "  /diag       - full diagnostic"
echo "  /strategy   - per-strategy P&L"
echo "  /live       - live-trading gates"
echo "  /restart    - restart bot/brain"
echo
echo "Backup your data weekly:"
echo "  tar -czf kotak-backup-\$(date +%Y%m%d).tar.gz /opt/kotak-neo-bot/data_cache/"
echo
echo "Update the bot:"
echo "  cd /opt/kotak-neo-bot && git pull"
echo "  systemctl restart kotak-bot"
