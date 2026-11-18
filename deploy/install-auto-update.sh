#!/usr/bin/env bash
# One-time: run deploy/auto-update.sh every 5 minutes (log: ~/reversal-update.log)
set -uo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"
chmod +x "$DIR/deploy/auto-update.sh"
LINE="*/5 * * * * $DIR/deploy/auto-update.sh >> \$HOME/reversal-update.log 2>&1"
EXISTING="$(crontab -l 2>/dev/null | grep -v 'deploy/auto-update.sh' || true)"
printf '%s\n%s\n' "$EXISTING" "$LINE" | sed '/^$/d' | crontab -
if crontab -l 2>/dev/null | grep -q 'deploy/auto-update.sh'; then
  echo "Auto-update installed: the server checks GitHub every 5 minutes."
else
  echo "ERROR: could not install the cron job" >&2
  exit 1
fi
