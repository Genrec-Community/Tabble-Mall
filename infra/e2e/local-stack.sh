#!/usr/bin/env bash
# Runs the whole stack for end-to-end tests WITHOUT Docker: Postgres (already running) + the API
# + the Next.js server + Nginx with the repo's real config on :8080. Playwright starts this via
# `webServer`; it stays in the foreground and cleans up after itself.
#
#   E2E_DATABASE_URL   default postgresql+asyncpg://postgres:test@localhost:5432/mallt_e2e
#   E2E_SKIP_BUILD=1   reuse the existing frontend build
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
RUN_DIR="${E2E_RUN_DIR:-/tmp/mallt-e2e}"
DB_URL="${E2E_DATABASE_URL:-postgresql+asyncpg://postgres:test@localhost:5432/mallt_e2e}"
PIDS=()

cleanup() {
  for pid in "${PIDS[@]:-}"; do [ -n "$pid" ] && kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

mkdir -p "$RUN_DIR"

# Fail loudly if something else already holds our ports (a stale server would serve old code).
for port in 3000 8000 8080; do
  if (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
    echo "[e2e] port $port is already in use; stop whatever is listening there first" >&2
    exit 1
  fi
done

echo "[e2e] fresh database"
(cd "$ROOT/backend" && DB_URL="$DB_URL" uv run python - <<'PY'
import asyncio, os, asyncpg
url = os.environ["DB_URL"].replace("+asyncpg", "")
base, _, name = url.rpartition("/")
async def main():
    conn = await asyncpg.connect(f"{base}/postgres")
    await conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    await conn.execute(f'CREATE DATABASE "{name}"')
    await conn.close()
asyncio.run(main())
PY
)
(cd "$ROOT/backend" && DATABASE_URL="$DB_URL" uv run alembic upgrade head)

echo "[e2e] api"
(
  cd "$ROOT/backend"
  # ENV=test is the only mode where a fixed OTP is honoured.
  ENV=test DATABASE_URL="$DB_URL" E2E_FIXED_OTP=123456 SMS_BACKEND=console REDIS_URL= \
    COOKIE_SECURE=false GOOGLE_CLIENT_ID= \
    exec uv run uvicorn mallt.main:create_app --factory --host 127.0.0.1 --port 8000 --proxy-headers
) >"$RUN_DIR/api.log" 2>&1 &
PIDS+=($!)

echo "[e2e] web"
if [ -z "${E2E_SKIP_BUILD:-}" ]; then (cd "$ROOT/frontend" && pnpm build >"$RUN_DIR/build.log" 2>&1); fi
STANDALONE="$ROOT/frontend/.next/standalone"
rm -rf "$STANDALONE/.next/static" "$STANDALONE/public"
cp -r "$ROOT/frontend/.next/static" "$STANDALONE/.next/static"
[ -d "$ROOT/frontend/public" ] && cp -r "$ROOT/frontend/public" "$STANDALONE/public"
(
  cd "$STANDALONE"
  API_INTERNAL_URL=http://127.0.0.1:8000 PORT=3000 HOSTNAME=127.0.0.1 exec node server.js
) >"$RUN_DIR/web.log" 2>&1 &
PIDS+=($!)

echo "[e2e] nginx"
CONF="$RUN_DIR/nginx.conf"
{
  echo "pid $RUN_DIR/nginx.pid; error_log $RUN_DIR/nginx-error.log;"
  sed -e 's/listen 80;/listen 8080;/' \
      -e 's/server api:8000/server 127.0.0.1:8000/' \
      -e 's/server web:3000/server 127.0.0.1:3000/' \
      -e 's/rate=60r\/m/rate=6000r\/m/' \
      -e "s#^http {#http {\n  access_log off;\n  client_body_temp_path $RUN_DIR/body; proxy_temp_path $RUN_DIR/proxy; fastcgi_temp_path $RUN_DIR/fcgi; uwsgi_temp_path $RUN_DIR/uwsgi; scgi_temp_path $RUN_DIR/scgi;#" \
      "$ROOT/infra/nginx/nginx.conf"
} >"$CONF"
nginx -c "$CONF" -g "daemon off;" &
PIDS+=($!)

for i in $(seq 1 120); do
  if curl -fsS http://127.0.0.1:8080/api/v1/health >/dev/null 2>&1 && curl -fsS -o /dev/null http://127.0.0.1:8080/login; then
    echo "[e2e] ready"
    break
  fi
  sleep 1
  [ "$i" = 120 ] && { echo "[e2e] stack did not become ready"; tail -n 30 "$RUN_DIR"/*.log; exit 1; }
done

wait -n "${PIDS[@]}"   # stay up until something dies or Playwright stops us
