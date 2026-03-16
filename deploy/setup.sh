#!/usr/bin/env bash
set -euo pipefail

# Polymarket Bot - Server Setup Script
# Run as root on a fresh Ubuntu 24.04 droplet

APP_DIR="/opt/polymarket-bot"
APP_USER="polymarket"

echo "=== Installing system packages ==="
apt-get update
apt-get install -y python3 python3-venv python3-pip git ufw sqlite3

echo "=== Creating $APP_USER user ==="
if ! id "$APP_USER" &>/dev/null; then
    useradd --system --create-home --shell /bin/bash "$APP_USER"
fi

echo "=== Cloning repository ==="
if [ ! -d "$APP_DIR" ]; then
    git clone https://github.com/harrymcdonagh/polymarket-bot.git "$APP_DIR"
else
    cd "$APP_DIR" && git pull
fi
chown -R "$APP_USER":"$APP_USER" "$APP_DIR"

echo "=== Setting up Python virtual environment ==="
sudo -u "$APP_USER" python3 -m venv "$APP_DIR/venv"
sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install -e "$APP_DIR"

echo "=== Creating data directory ==="
sudo -u "$APP_USER" mkdir -p "$APP_DIR/data"

echo "=== Setting up .env ==="
if [ ! -f "$APP_DIR/.env" ]; then
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"
    chown "$APP_USER":"$APP_USER" "$APP_DIR/.env"
    chmod 600 "$APP_DIR/.env"
    echo ">>> EDIT $APP_DIR/.env with your API keys <<<"
fi

echo "=== Installing systemd services ==="
cp "$APP_DIR/deploy/polymarket-bot.service" /etc/systemd/system/
cp "$APP_DIR/deploy/polymarket-web.service" /etc/systemd/system/
cp "$APP_DIR/deploy/polymarket-settler.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable polymarket-bot polymarket-web polymarket-settler

echo "=== Configuring firewall ==="
ufw allow OpenSSH
ufw allow 8050/tcp
ufw --force enable

echo "=== Configuring journald log retention ==="
mkdir -p /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/polymarket.conf << 'CONF'
[Journal]
SystemMaxUse=500M
CONF
systemctl restart systemd-journald

echo "=== Setting up daily backup cron ==="
cat > /etc/cron.daily/polymarket-backup << 'CRON'
#!/bin/bash
sqlite3 /opt/polymarket-bot/data/polymarket.db ".backup /opt/polymarket-bot/data/backup-$(date +%Y%m%d).db"
chown polymarket:polymarket /opt/polymarket-bot/data/backup-*.db
find /opt/polymarket-bot/data/ -name "backup-*.db" -mtime +7 -delete
CRON
chmod +x /etc/cron.daily/polymarket-backup

echo ""
echo "=== Setup complete! ==="
echo ""
echo "Next steps:"
echo "  1. Edit /opt/polymarket-bot/.env with your API keys"
echo "  2. Start services:"
echo "     sudo systemctl start polymarket-bot polymarket-web polymarket-settler"
echo "  3. Check status:"
echo "     sudo systemctl status polymarket-bot"
echo "  4. View logs:"
echo "     journalctl -u polymarket-bot -f"
