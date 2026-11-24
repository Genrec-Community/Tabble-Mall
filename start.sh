#!/usr/bin/env bash
# macOS / Linux equivalent of start.bat. Needs uv (https://docs.astral.sh/uv/) and Node 22.
set -euo pipefail
cd "$(dirname "$0")"
exec uv run --no-dev --project backend python local/run_local.py
