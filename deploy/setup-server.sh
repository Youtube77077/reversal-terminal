#!/usr/bin/env bash
# One-time setup on a fresh Ubuntu 22.04/24.04 VPS (recommended: Amsterdam region).
# Usage (as root or a sudo user):
#   curl -fsSL https://raw.githubusercontent.com/<you>/<repo>/main/deploy/setup-server.sh -o setup.sh   # private repo: copy it over instead
#   bash setup.sh
set -euo pipefail

echo "==> Installing Docker"
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi

echo "==> Getting the code"
if [ ! -d reversal-terminal ]; then
  read -rp "GitHub repo (owner/name): " REPO
  read -rsp "GitHub token with repo read access (not stored): " TOKEN; echo
  git clone "https://${TOKEN}@github.com/${REPO}.git" reversal-terminal
  git -C reversal-terminal remote set-url origin "https://github.com/${REPO}.git"
fi
cd reversal-terminal

if [ ! -f .env ]; then
  cp .env.example .env
  read -rsp "Choose the website/app password: " PW; echo
  sed -i "s|^APP_PASSWORD=.*|APP_PASSWORD=${PW}|" .env
  sed -i "s|^SESSION_SECRET=.*|SESSION_SECRET=$(openssl rand -hex 32)|" .env
  sed -i "s|^EXECUTOR_TOKEN=.*|EXECUTOR_TOKEN=$(openssl rand -hex 24)|" .env
  chmod 600 .env
  echo "    .env created (chmod 600). Add Polymarket keys later with: nano $(pwd)/.env"
fi

IP=$(curl -fsSL https://api.ipify.org)
DOMAIN_DEFAULT="${IP//./-}.sslip.io"
read -rp "Domain for HTTPS [${DOMAIN_DEFAULT}]: " DOMAIN
DOMAIN=${DOMAIN:-$DOMAIN_DEFAULT}
echo "DOMAIN=${DOMAIN}" > .compose.env

echo "==> Building and starting (first build takes a few minutes)"
docker compose --env-file .compose.env up -d --build

echo
echo "Done. Open https://${DOMAIN} on your phone or PC and log in."
echo "In the iPhone app, enter: https://${DOMAIN}"
echo "Update later with:  cd $(pwd) && git pull && docker compose --env-file .compose.env up -d --build"
