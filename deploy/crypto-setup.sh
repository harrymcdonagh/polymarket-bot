#!/usr/bin/env bash
set -euo pipefail

# Polymarket Crypto Bot - Setup Script
# Run from /opt/polymarket-bot after main bot is set up

CRYPTO_DIR="/opt/polymarket-bot/crypto"
APP_USER="polymarket"

echo "=== Setting up crypto bot ==="

echo "=== Creating Python virtual environment ==="
sudo -u "$APP_USER" python3 -m venv "$CRYPTO_DIR/venv"
sudo -u "$APP_USER" "$CRYPTO_DIR/venv/bin/pip" install -e "$CRYPTO_DIR"

echo "=== Setting up .env ==="
if [ ! -f "$CRYPTO_DIR/.env" ]; then
    cp "$CRYPTO_DIR/.env.example" "$CRYPTO_DIR/.env"
    # Point DB to shared database
    sed -i 's|DB_PATH=.*|DB_PATH=/opt/polymarket-bot/data/polymarket.db|' "$CRYPTO_DIR/.env"
    chown "$APP_USER":"$APP_USER" "$CRYPTO_DIR/.env"
    chmod 600 "$CRYPTO_DIR/.env"
    echo ">>> EDIT $CRYPTO_DIR/.env with your settings <<<"
fi

echo "=== Installing systemd services ==="
cp "$CRYPTO_DIR/../deploy/polymarket-crypto-bot.service" /etc/systemd/system/
cp "$CRYPTO_DIR/../deploy/polymarket-crypto-settler.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable polymarket-crypto-bot polymarket-crypto-settler

echo ""
echo "=== Setup complete! ==="
echo "  1. Edit $CRYPTO_DIR/.env"
echo "  2. Start: sudo systemctl start polymarket-crypto-bot polymarket-crypto-settler"
echo "  3. Logs: journalctl -u polymarket-crypto-bot -f"
