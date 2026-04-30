#!/usr/bin/env bash
# deploy/oracle/setup.sh — one-shot bootstrap on a fresh Ubuntu 22.04 ARM VM.
# Run after first SSH:
#   curl -fsSL https://raw.githubusercontent.com/kushagra93/hyperliquid-perps-analyzer/main/deploy/oracle/setup.sh | bash
# or, if you've already cloned the repo:
#   bash deploy/oracle/setup.sh
#
# What this does:
#  - Sets the system timezone to Asia/Kolkata
#  - Installs python3-pip, python3-venv, git, build deps
#  - Clones the repo (idempotent; skips if already present)
#  - Creates .venv and installs requirements
#  - Drops a starter .env from .env.example (you still must fill it in)
#  - Installs and enables the systemd unit
# Idempotent: safe to re-run.

set -euo pipefail

REPO_URL="https://github.com/kushagra93/hyperliquid-perps-analyzer.git"
APP_DIR="$HOME/hyperliquid-perps-analyzer"

log() { printf "\n\033[1;36m▶ %s\033[0m\n" "$*"; }

log "Setting timezone to Asia/Kolkata"
sudo timedatectl set-timezone Asia/Kolkata

log "apt update + install"
sudo apt-get update -y
sudo apt-get install -y python3-pip python3-venv git build-essential libffi-dev libssl-dev

log "Clone repo (skip if present)"
if [[ ! -d "$APP_DIR/.git" ]]; then
  git clone "$REPO_URL" "$APP_DIR"
else
  echo "  $APP_DIR already exists; skipping clone."
fi

cd "$APP_DIR"
log "Pull latest"
git pull --ff-only

log "Create venv + install deps"
if [[ ! -d ".venv" ]]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

log "Seed .env (only if missing)"
if [[ ! -f ".env" ]]; then
  cp deploy/oracle/.env.example .env
  echo "  Created .env from template — edit it now: nano $APP_DIR/.env"
fi
chmod 600 .env

log "Install systemd unit"
sudo cp deploy/oracle/hl-analyzer.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable hl-analyzer

log "Setup logrotate for alerts.jsonl"
sudo tee /etc/logrotate.d/hl-analyzer >/dev/null <<EOF
$APP_DIR/eval/alerts.jsonl {
  weekly
  rotate 8
  compress
  missingok
  notifempty
  copytruncate
}
EOF

cat <<EOF

✅ Bootstrap complete.

Next steps:
  1. nano $APP_DIR/.env                 # paste your API keys
  2. (if using GOOGLE_CREDENTIALS_FILE)  scp the JSON onto this host, then:
       chmod 600 $APP_DIR/credentials.json
  3. sudo systemctl start hl-analyzer
  4. journalctl -u hl-analyzer -f       # watch logs land

EOF
