#!/usr/bin/env bash
# One-time: run deploy/auto-update.sh every 5 minutes (log: ~/reversal-update.log)
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"
chmod +x "$DIR/deploy/auto-update.sh"
( crontab -l 2>/dev/null | grep -v reversal-terminal/deploy/auto-update.sh ; \
  echo "*/5 * * * * $DIR/deploy/auto-update.sh >> \$HOME/reversal-update.log 2>&1" ) | crontab -
echo "Auto-update installed: the server checks GitHub every 5 minutes."
