#!/usr/bin/env bash
# With arguments (e.g. the one-off bootstrap task) run them as given.
# Without: migrate, then run FastAPI (127.0.0.1) and Next.js (all interfaces) and stop both cleanly.
set -euo pipefail
if [ "$#" -gt 0 ]; then exec "$@"; fi

cd /app/backend
python -m scripts.bootstrap migrate

python -m uvicorn app.main:create_app --factory --no-proxy-headers --host 127.0.0.1 --port "${API_PORT}" \
  --timeout-graceful-shutdown 20 &
api=$!
(cd /app/frontend && exec node node_modules/next/dist/bin/next start -H 0.0.0.0 -p "${WEB_PORT}") &
web=$!

stop() {
  trap - TERM INT
  kill -TERM "$web" "$api" 2>/dev/null || true
  wait "$web" "$api" 2>/dev/null || true
  exit 0
}
trap stop TERM INT

# if either process dies, stop the other and report failure so the platform replaces the task
wait -n "$api" "$web" || true
echo "a server process exited; shutting down" >&2
kill -TERM "$web" "$api" 2>/dev/null || true
wait 2>/dev/null || true
exit 1
