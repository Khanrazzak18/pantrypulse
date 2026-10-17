# One production image: Next.js on 8080 (public) and FastAPI on 127.0.0.1:8000 (behind the /api rewrite).
# Build:  docker buildx build --platform linux/arm64 -t pantrypulse .

FROM node:24-bookworm-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# next.config.ts bakes the /api rewrite target in at build time
ENV API_PORT=8000 NEXT_TELEMETRY_DISABLED=1
RUN npm run build && npm prune --omit=dev

FROM python:3.12-slim-bookworm AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 tini \
    && rm -rf /var/lib/apt/lists/*
COPY --from=web /usr/local/bin/node /usr/local/bin/node
WORKDIR /app/backend
COPY backend/pyproject.toml ./
# install only the dependencies first so this layer is cached across code changes
RUN python - <<'PY' > /tmp/req.txt
import tomllib
print("\n".join(tomllib.load(open("pyproject.toml", "rb"))["project"]["dependencies"]))
PY
RUN pip install --no-cache-dir -r /tmp/req.txt
COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./
COPY backend/scripts ./scripts
COPY --from=web /web /app/frontend
COPY deploy/entrypoint.sh /app/entrypoint.sh
RUN useradd --system --uid 10001 --home /app app && chmod +x /app/entrypoint.sh \
    && mkdir -p /app/backend/var && chown -R app /app/backend/var
USER app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 NODE_ENV=production \
    API_PORT=8000 WEB_PORT=8080 PYTHONPATH=/app/backend
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8080/api/health', timeout=4)"
ENTRYPOINT ["/usr/bin/tini", "--", "/app/entrypoint.sh"]
