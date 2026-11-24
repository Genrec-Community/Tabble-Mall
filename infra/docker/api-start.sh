#!/bin/sh
# API container entrypoint. Hosts without a release step (e.g. Render free plan) set
# MIGRATE_ON_START=true to apply migrations before serving; docker compose leaves it unset.
set -e
if [ "${MIGRATE_ON_START:-false}" = "true" ]; then
  alembic upgrade head
fi
exec uvicorn mallt.main:create_app --factory --host 0.0.0.0 --port "${PORT:-8000}" \
  --proxy-headers --forwarded-allow-ips='*'
