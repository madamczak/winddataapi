#!/usr/bin/env bash
# =============================================================================
# pi2.sh — Raspberry Pi 2 crawler runner
#
# Patterns assigned to this Pi:
#   • rated_power          (kelmarsh)   – very stable near-nameplate power
#   • partial_performance  (kelmarsh)   – curtailment / sub-rated operation
#
# Manual run:
#   WINDDATA_API=https://your-api.onrender.com bash runners/pi2.sh
# =============================================================================
set -euo pipefail

API="${WINDDATA_API:-https://winddataapi-backend.onrender.com}"
FARM="${WIND_FARM:-kelmarsh}"
ITERATIONS="${CRAWL_ITERATIONS:-2}"    # 2 slots × ~3 min delay ≈ 6 min per pattern
DELAY="${CRAWL_DELAY:-180}"            # 3 min between slots — no rush
TURBINE_DELAY="${CRAWL_TURBINE_DELAY:-1}"  # 1 s between turbines once first matches
LOCK="/tmp/apicrawler_pi2.lock"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
CRAWL="$REPO_DIR/crawler/apicrawler/crawl.py"
RESULTS_DIR="$REPO_DIR/crawler/apicrawler/results"
LOG_DIR="$REPO_DIR/runners/logs"
LOG_FILE="$LOG_DIR/pi2.log"

mkdir -p "$RESULTS_DIR" "$LOG_DIR"

if [ -f "$REPO_DIR/.venv/bin/python" ]; then
    PYTHON="$REPO_DIR/.venv/bin/python"
elif command -v python3 &>/dev/null; then
    PYTHON="python3"
else
    echo "ERROR: python3 not found" >&2; exit 1
fi

exec 9>"$LOCK"
if ! flock -n 9; then
    echo "$(date -u +%FT%TZ)  [pi2] Previous run still active — skipping." \
        | tee -a "$LOG_FILE"
    exit 0
fi

if [ -f "$LOG_FILE" ] && [ "$(wc -l < "$LOG_FILE")" -gt 500 ]; then
    tail -n 400 "$LOG_FILE" > "${LOG_FILE}.tmp" && mv "${LOG_FILE}.tmp" "$LOG_FILE"
fi

# Offset seed by a large prime so Pi 2 samples different territory from Pi 1
SEED=$(( $(date +%s) + 2000003 ))

echo "" | tee -a "$LOG_FILE"
echo "======================================" | tee -a "$LOG_FILE"
echo "$(date -u +%FT%TZ)  [pi2] Starting — seed=$SEED  api=$API" \
    | tee -a "$LOG_FILE"

echo "$(date -u +%FT%TZ)  [pi2] Running: rated_power" | tee -a "$LOG_FILE"
"$PYTHON" "$CRAWL" \
    --api          "$API" \
    --farm         "$FARM" \
    --pattern      rated_power \
    --iterations   "$ITERATIONS" \
    --delay        "$DELAY" \
    --turbine-delay "$TURBINE_DELAY" \
    --seed         "$SEED" \
    2>&1 | tee -a "$LOG_FILE"

echo "$(date -u +%FT%TZ)  [pi2] Running: partial_performance" | tee -a "$LOG_FILE"
"$PYTHON" "$CRAWL" \
    --api          "$API" \
    --farm         "$FARM" \
    --pattern      partial_performance \
    --iterations   "$ITERATIONS" \
    --delay        "$DELAY" \
    --turbine-delay "$TURBINE_DELAY" \
    --seed         $((SEED + 1000000)) \
    2>&1 | tee -a "$LOG_FILE"

echo "$(date -u +%FT%TZ)  [pi2] Done." | tee -a "$LOG_FILE"

