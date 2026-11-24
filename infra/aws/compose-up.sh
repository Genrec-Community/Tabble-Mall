#!/bin/bash
# Run on the instance from /opt/tabble: build and start the stack with the overrides that this
# deployment's .env selects (written from SSM by tabble-deploy). Extra arguments go to compose,
# e.g. `infra/aws/compose-up.sh exec api python -m mallt.cli seed-admin`.
set -euo pipefail
cd "$(dirname "$0")/../.."
files=(-f docker-compose.yml -f infra/aws/docker-compose.aws.yml)
services=(nginx web api)
if grep -q '^LOCAL_DB=true$' .env; then files+=(-f infra/aws/docker-compose.localdb.yml); fi
if grep -q '^EDGE=caddy$' .env; then files+=(-f infra/aws/docker-compose.caddy.yml); services+=(caddy); fi
if [ $# -gt 0 ]; then exec docker compose "${files[@]}" "$@"; fi
docker compose "${files[@]}" up -d --build --remove-orphans "${services[@]}"
