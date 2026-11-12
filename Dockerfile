# One container for hosts that give you a single web port (Render, Fly, Railway, a small VPS).
# It runs the FastAPI API, the Next.js dashboard and a small gateway that serves both on $PORT.
# The full Kafka / Flink / ClickHouse / Temporal stack stays in docker-compose.yml.
FROM node:22-bookworm-slim AS web
WORKDIR /app/apps/web
COPY apps/web/package*.json ./
RUN npm ci
COPY apps/web ./
ENV NEXT_PUBLIC_API_URL=/api API_INTERNAL_URL=http://127.0.0.1:8000 NEXT_TELEMETRY_DISABLED=1
RUN npm run build && npm prune --omit=dev

FROM python:3.12-slim-bookworm
COPY --from=web /usr/local/bin/node /usr/local/bin/node
COPY --from=web /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm
WORKDIR /app
COPY services/api/pyproject.toml services/api/pyproject.toml
COPY services/api/app services/api/app
RUN pip install --no-cache-dir ./services/api
COPY --from=web /app/apps/web apps/web
COPY replit_start.py replit_gateway.mjs ./
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PYTHONUNBUFFERED=1 \
    SQLITE_FALLBACK_URL=sqlite+aiosqlite:////tmp/callpay.db
EXPOSE 3000
CMD ["python", "replit_start.py"]
