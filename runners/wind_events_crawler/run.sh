#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
WORKER_DIR="$REPO_DIR/crawler/wind_events_crawler"

if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    # shellcheck source=/dev/null
    . "$SCRIPT_DIR/.env"
    set +a
fi

if command -v uv >/dev/null 2>&1; then
    UV_BIN="uv"
elif command -v python3 >/dev/null 2>&1; then
    UV_BIN="python3 -m uv"
else
    echo "ERROR: uv (or python3 -m uv) is required to run wind-events-crawler" >&2
    exit 1
fi

mkdir -p "$REPO_DIR/crawler/output/wind_events_crawler"

# Canonical packaged entrypoint: uv run --directory "$WORKER_DIR" wind-events-crawler
exec $UV_BIN run --directory "$WORKER_DIR" wind-events-crawler
