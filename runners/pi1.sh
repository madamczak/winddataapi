#!/usr/bin/env bash
# =============================================================================
# pi1.sh — Raspberry Pi 1 crawler runner
#
# Patterns assigned to this Pi:
#   • high_wind_full_spin  (kelmarsh)   – near-rated power, high wind
#   • farm_stopped         (kelmarsh)   – entire farm offline
#
# Copy this whole repo (or just crawler/apicrawler + runners) to the Pi,
# run  bash runners/install.sh  once, then the crontab entry will fire
# this script every 10 minutes automatically.
#
# Manual run:
#   WINDDATA_API=https://your-api.onrender.com bash runners/pi1.sh
# =============================================================================
set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
API="${WINDDATA_API:-https://your-api.onrender.com}"
FARM="${WIND_FARM:-kelmarsh}"
ITERATIONS="${CRAWL_ITERATIONS:-2}"    # 2 slots × ~3 min delay ≈ 6 min per pattern
DELAY="${CRAWL_DELAY:-180}"            # 3 min between API calls — no rush
LOCK="/tmp/apicrawler_pi1.lock"

# ── Resolve paths relative to this script ────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
CRAWL="$REPO_DIR/crawler/apicrawler/crawl.py"
RESULTS_DIR="$REPO_DIR/crawler/apicrawler/results"
LOG_DIR="$REPO_DIR/runners/logs"
LOG_FILE="$LOG_DIR/pi1.log"

mkdir -p "$RESULTS_DIR" "$LOG_DIR"

# ── Python: prefer venv, fall back to system python3 ─────────────────────────
if [ -f "$REPO_DIR/.venv/bin/python" ]; then
    PYTHON="$REPO_DIR/.venv/bin/python"
elif command -v python3 &>/dev/null; then
    PYTHON="python3"
else
    echo "ERROR: python3 not found" >&2; exit 1
fi

# ── Prevent overlapping runs ──────────────────────────────────────────────────
exec 9>"$LOCK"
if ! flock -n 9; then
    echo "$(date -u +%FT%TZ)  [pi1] Previous run still active — skipping." \
        | tee -a "$LOG_FILE"
    exit 0
fi

# ── Log rotation: keep last 500 lines ─────────────────────────────────────────
if [ -f "$LOG_FILE" ] && [ "$(wc -l < "$LOG_FILE")" -gt 500 ]; then
    tail -n 400 "$LOG_FILE" > "${LOG_FILE}.tmp" && mv "${LOG_FILE}.tmp" "$LOG_FILE"
fi

# ── Use timestamp as seed so each cron invocation explores new territory ──────
SEED=$(date +%s)

echo "" | tee -a "$LOG_FILE"
echo "======================================" | tee -a "$LOG_FILE"
echo "$(date -u +%FT%TZ)  [pi1] Starting — seed=$SEED  api=$API" \
    | tee -a "$LOG_FILE"

# ── Pattern 1: high_wind_full_spin ────────────────────────────────────────────
echo "$(date -u +%FT%TZ)  [pi1] Running: high_wind_full_spin" | tee -a "$LOG_FILE"
"$PYTHON" "$CRAWL" \
    --api          "$API" \
    --farm         "$FARM" \
    --pattern      high_wind_full_spin \
    --iterations   "$ITERATIONS" \
    --delay        "$DELAY" \
    --seed         "$SEED" \
    2>&1 | tee -a "$LOG_FILE"

# ── Pattern 2: farm_stopped ───────────────────────────────────────────────────
echo "$(date -u +%FT%TZ)  [pi1] Running: farm_stopped" | tee -a "$LOG_FILE"
"$PYTHON" "$CRAWL" \
    --api          "$API" \
    --farm         "$FARM" \
    --pattern      farm_stopped \
    --iterations   "$ITERATIONS" \
    --delay        "$DELAY" \
    --seed         $((SEED + 1000000)) \
    2>&1 | tee -a "$LOG_FILE"

echo "$(date -u +%FT%TZ)  [pi1] Done." | tee -a "$LOG_FILE"

