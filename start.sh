#!/usr/bin/env bash
# macOS / Linux equivalent of start.bat.
set -euo pipefail
cd "$(dirname "$0")"
COMPOSE=(docker compose -p mallt -f docker-compose.yml -f local/docker-compose.local.yml)
"${COMPOSE[@]}" up -d --build --wait
"${COMPOSE[@]}" exec -T api python local/seed_demo.py > /tmp/mallt-seed.txt
grep -q "MallT demo logins" /tmp/mallt-seed.txt && cp /tmp/mallt-seed.txt demo-logins.txt
cat demo-logins.txt 2>/dev/null || cat /tmp/mallt-seed.txt
echo; echo "Customer page: http://localhost:8080/m/demo-mall   Staff: http://localhost:8080/login"
