#!/usr/bin/env bash

set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${APP_DIR}/.venv"
ENV_FILE="${APP_DIR}/.env"
SERVICE_NAME="${SERVICE_NAME:-kupovinabot}"
APP_USER="${APP_USER:-$(whoami)}"
APP_GROUP="${APP_GROUP:-$(id -gn)}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
DB_PATH_DEFAULT="${APP_DIR}/shopping_bot.db"
SYSTEMD_UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}.service"

require_command() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "Missing required command: $1" >&2
        exit 1
    fi
}

require_command "${PYTHON_BIN}"
require_command sudo
require_command systemctl

echo "Project directory: ${APP_DIR}"
echo "Service name: ${SERVICE_NAME}"
echo "App user: ${APP_USER}"

if [ ! -d "${VENV_DIR}" ]; then
    echo "Creating virtual environment..."
    "${PYTHON_BIN}" -m venv "${VENV_DIR}"
fi

echo "Installing Python dependencies..."
"${VENV_DIR}/bin/pip" install --upgrade pip
"${VENV_DIR}/bin/pip" install -r "${APP_DIR}/requirements.txt"

if [ ! -f "${ENV_FILE}" ]; then
    echo "Creating .env template..."
    cat > "${ENV_FILE}" <<EOF
TELEGRAM_BOT_TOKEN=PUT_YOUR_TOKEN_HERE
SHOPPING_BOT_DB_PATH=${DB_PATH_DEFAULT}
EOF
    echo "Created ${ENV_FILE}. Update TELEGRAM_BOT_TOKEN before using the bot."
fi

echo "Writing systemd unit..."
sudo tee "${SYSTEMD_UNIT_PATH}" >/dev/null <<EOF
[Unit]
Description=Kupovina Telegram Bot
After=network.target

[Service]
Type=simple
User=${APP_USER}
Group=${APP_GROUP}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${VENV_DIR}/bin/python ${APP_DIR}/main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

echo "Reloading systemd and enabling service..."
sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}"
sudo systemctl restart "${SERVICE_NAME}"

echo
echo "Deployment finished."
echo "Service status:"
sudo systemctl --no-pager --full status "${SERVICE_NAME}" || true
echo
echo "If this is the first deploy, edit ${ENV_FILE} and set TELEGRAM_BOT_TOKEN."
