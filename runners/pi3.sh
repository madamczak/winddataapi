#!/usr/bin/env bash
# =============================================================================
# pi3.sh — Raspberry Pi 3 crawler runner
#
# Patterns assigned to this Pi:
#   • blade_rpm_15    (kelmarsh turbines 2-6, penmanshiel all)
#   • low_wind_cutin  (kelmarsh + penmanshiel)
#   • high_nacelle_temp (kelmarsh + penmanshiel)
#
# Note: kelmarsh turbine_1 excluded from blade_rpm_15 — its SCADA labels for
#       RPM columns are swapped vs all other turbines and neither column falls
#       in the expected blade-RPM physical range [5, 25].
#       With the 70% threshold this exclusion is optional, but kept for clarity.
#
# Manual run:
#   WINDDATA_API=https://your-api.onrender.com bash runners/pi3.sh
# =============================================================================
set -euo pipefail

API="${WINDDATA_API:-https://winddataapi-backend.onrender.com}"
FARM="${WIND_FARM:-kelmarsh}"
ITERATIONS="${CRAWL_ITERATIONS:-1}"    # 1 slot × 3 patterns × ~3 min delay ≈ 9 min
DELAY="${CRAWL_DELAY:-180}"            # 3 min between slots — no rush
TURBINE_DELAY="${CRAWL_TURBINE_DELAY:-1}"  # 1 s between turbines once first matches
LOCK="/tmp/apicrawler_pi3.lock"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
CRAWL="$REPO_DIR/crawler/apicrawler/crawl.py"
RESULTS_DIR="$REPO_DIR/crawler/apicrawler/results"
LOG_DIR="$REPO_DIR/runners/logs"
LOG_FILE="$LOG_DIR/pi3.log"

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
    echo "$(date -u +%FT%TZ)  [pi3] Previous run still active — skipping." \
        | tee -a "$LOG_FILE"
    exit 0
fi

if [ -f "$LOG_FILE" ] && [ "$(wc -l < "$LOG_FILE")" -gt 500 ]; then
    tail -n 400 "$LOG_FILE" > "${LOG_FILE}.tmp" && mv "${LOG_FILE}.tmp" "$LOG_FILE"
fi

# Offset seed by a different large prime so Pi 3 samples yet-different territory
SEED=$(( $(date +%s) + 4000037 ))

echo "" | tee -a "$LOG_FILE"
echo "======================================" | tee -a "$LOG_FILE"
echo "$(date -u +%FT%TZ)  [pi3] Starting — seed=$SEED  api=$API" \
    | tee -a "$LOG_FILE"

# turbine_1 excluded for blade_rpm_15 on kelmarsh (SCADA labelling inconsistency — see README)
echo "$(date -u +%FT%TZ)  [pi3] Running: blade_rpm_15 (kelmarsh, turbines 2-6)" | tee -a "$LOG_FILE"
"$PYTHON" "$CRAWL" \
    --api          "$API" \
    --farm         kelmarsh \
    --pattern      blade_rpm_15 \
    --iterations   "$ITERATIONS" \
    --delay        "$DELAY" \
    --turbine-delay "$TURBINE_DELAY" \
    --seed         "$SEED" \
    --turbines     turbine_2 turbine_3 turbine_4 turbine_5 turbine_6 \
    2>&1 | tee -a "$LOG_FILE"

echo "$(date -u +%FT%TZ)  [pi3] Running: blade_rpm_15 (penmanshiel)" | tee -a "$LOG_FILE"
"$PYTHON" "$CRAWL" \
    --api          "$API" \
    --farm         penmanshiel \
    --pattern      blade_rpm_15 \
    --iterations   "$ITERATIONS" \
    --delay        "$DELAY" \
    --turbine-delay "$TURBINE_DELAY" \
    --seed         $((SEED + 500000)) \
    2>&1 | tee -a "$LOG_FILE"

echo "$(date -u +%FT%TZ)  [pi3] Running: low_wind_cutin (kelmarsh)" | tee -a "$LOG_FILE"
"$PYTHON" "$CRAWL" \
    --api          "$API" \
    --farm         kelmarsh \
    --pattern      low_wind_cutin \
    --iterations   "$ITERATIONS" \
    --delay        "$DELAY" \
    --turbine-delay "$TURBINE_DELAY" \
    --seed         $((SEED + 1000000)) \
    2>&1 | tee -a "$LOG_FILE"

echo "$(date -u +%FT%TZ)  [pi3] Running: low_wind_cutin (penmanshiel)" | tee -a "$LOG_FILE"
"$PYTHON" "$CRAWL" \
    --api          "$API" \
    --farm         penmanshiel \
    --pattern      low_wind_cutin \
    --iterations   "$ITERATIONS" \
    --delay        "$DELAY" \
    --turbine-delay "$TURBINE_DELAY" \
    --seed         $((SEED + 1500000)) \
    2>&1 | tee -a "$LOG_FILE"

echo "$(date -u +%FT%TZ)  [pi3] Running: high_nacelle_temp (kelmarsh)" | tee -a "$LOG_FILE"
"$PYTHON" "$CRAWL" \
    --api          "$API" \
    --farm         kelmarsh \
    --pattern      high_nacelle_temp \
    --iterations   "$ITERATIONS" \
    --delay        "$DELAY" \
    --turbine-delay "$TURBINE_DELAY" \
    --seed         $((SEED + 2000000)) \
    2>&1 | tee -a "$LOG_FILE"

echo "$(date -u +%FT%TZ)  [pi3] Running: high_nacelle_temp (penmanshiel)" | tee -a "$LOG_FILE"
"$PYTHON" "$CRAWL" \
    --api          "$API" \
    --farm         penmanshiel \
    --pattern      high_nacelle_temp \
    --iterations   "$ITERATIONS" \
    --delay        "$DELAY" \
    --turbine-delay "$TURBINE_DELAY" \
    --seed         $((SEED + 2500000)) \
    2>&1 | tee -a "$LOG_FILE"

echo "$(date -u +%FT%TZ)  [pi3] Done." | tee -a "$LOG_FILE"

