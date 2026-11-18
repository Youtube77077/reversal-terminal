#!/usr/bin/env bash
# Checks GitHub for new commits and rebuilds the bot when something changed.
# Installed as a cron job (every 5 minutes) by:  bash deploy/install-auto-update.sh
set -euo pipefail
cd "$(dirname "$0")/.."
exec 9>/tmp/reversal-update.lock
flock -n 9 || exit 0                       # skip if a previous update is still running
git fetch -q origin main
if [ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main)" ]; then
  echo "$(date -u +%FT%TZ) updating $(git rev-parse --short HEAD) -> $(git rev-parse --short origin/main)"
  git reset -q --hard origin/main
  # never let a stuck build block future updates
  if ! timeout 20m docker compose --env-file .compose.env up -d --build --remove-orphans; then
    echo "$(date -u +%FT%TZ) build failed or timed out — will retry next run"
    git reset -q --hard HEAD@{1} || true   # go back so the next run retries this update
    exit 1
  fi
  echo "$(date -u +%FT%TZ) now running $(git rev-parse --short HEAD)"
  docker image prune -f >/dev/null 2>&1 || true
fi
