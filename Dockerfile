# REVERSAL TERMINAL — single container: web UI + API + collector + paper engine + live executor.
# Build:  docker build -t reversal-terminal .
# Run:    docker compose up -d   (see docker-compose.yml / DEPLOY.md)

# ---------- 1) build the static web app ----------
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- 2) live executor dependencies ----------
FROM node:22-slim AS executor
WORKDIR /executor
COPY executor/package.json executor/package-lock.json ./
RUN npm ci --omit=dev --no-audit --no-fund
COPY executor/index.mjs ./

# ---------- 3) runtime ----------
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    API_HOST=0.0.0.0 API_PORT=8000 SERVE_FRONTEND=true \
    DATA_DIR=/app/backend/data
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 ca-certificates tini \
    && rm -rf /var/lib/apt/lists/*
COPY --from=node:22-slim /usr/local/bin/node /usr/local/bin/node
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ backend/
COPY --from=web /web/out frontend/out
COPY --from=executor /executor executor/
COPY deploy/start.sh /app/start.sh
RUN chmod +x /app/start.sh && mkdir -p /app/backend/data
VOLUME ["/app/backend/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/auth/status',timeout=4)"
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/app/start.sh"]
