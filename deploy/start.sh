#!/bin/sh
# Starts the live executor (supervised, restarts on crash) and the API/collector.
set -e
cd /app

if [ -z "$EXECUTOR_TOKEN" ]; then
  # backend and executor share this process environment, so a per-boot token is fine
  EXECUTOR_TOKEN=$(python -c "import secrets;print(secrets.token_hex(24))")
  export EXECUTOR_TOKEN
fi

(
  while true; do
    node /app/executor/index.mjs || true
    echo "[start] executor exited; restarting in 5s"
    sleep 5
  done
) &

cd /app/backend
exec python -m uvicorn app.main:app --host "${API_HOST:-0.0.0.0}" --port "${API_PORT:-8000}" \
  --proxy-headers --forwarded-allow-ips="*"
