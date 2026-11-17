#!/usr/bin/env bash
# One-time setup on a fresh Ubuntu 22.04/24.04 server.
# Works on Oracle Cloud "Always Free" (Ampere ARM, user "ubuntu") and any normal VPS.
#   scp deploy/setup-server.sh ubuntu@SERVER_IP:~   then   ssh ubuntu@SERVER_IP 'bash setup-server.sh'
set -euo pipefail
SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"

echo "==> Installing Docker"
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | $SUDO sh
  $SUDO usermod -aG docker "$(whoami)" || true
fi

echo "==> Opening ports 80/443 in the OS firewall (Oracle images block them by default)"
if command -v iptables >/dev/null; then
  for p in 80 443; do
    $SUDO iptables -C INPUT -p tcp --dport $p -j ACCEPT 2>/dev/null || $SUDO iptables -I INPUT 5 -p tcp --dport $p -j ACCEPT
  done
  if command -v netfilter-persistent >/dev/null; then $SUDO netfilter-persistent save || true; fi
fi

echo "==> Getting the code"
if [ ! -d reversal-terminal ]; then
  read -rp "GitHub repo (owner/name): " REPO
  read -rsp "GitHub token with read access to that repo (not stored): " TOKEN; echo
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
  echo "    .env created. Add Polymarket keys later in the app (Live trading -> API keys)."
fi

IP=$(curl -fsSL https://api.ipify.org)
DOMAIN_DEFAULT="${IP//./-}.sslip.io"
read -rp "Domain for HTTPS [${DOMAIN_DEFAULT}]: " DOMAIN
DOMAIN=${DOMAIN:-$DOMAIN_DEFAULT}
echo "DOMAIN=${DOMAIN}" > .compose.env

echo "==> Building and starting (first build takes ~5-10 minutes)"
$SUDO docker compose --env-file .compose.env up -d --build

echo
echo "Done. Open https://${DOMAIN} on your phone or PC and log in."
echo "iPhone app: enter https://${DOMAIN}"
echo "Update later:  cd $(pwd) && git pull && $SUDO docker compose --env-file .compose.env up -d --build"
echo "Oracle Cloud: also allow TCP 80 and 443 in Networking -> VCN -> Security List -> Ingress Rules (source 0.0.0.0/0)."
