#!/usr/bin/env bash
# macOS / Linux equivalent of start.bat. Needs uv (https://docs.astral.sh/uv/) and Node 22.
set -euo pipefail
cd "$(dirname "$0")"
if [ "${1:-}" != "--no-update" ] && [ "${1:-}" != "--updated" ]; then
  uv run -q --no-project --python 3.12 python local/update.py
  exec "$0" --updated
fi
exec uv run --no-dev --project backend python local/run_local.py
