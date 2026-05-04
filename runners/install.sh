#!/usr/bin/env bash
# =============================================================================
# install.sh — one-time setup on a fresh Raspberry Pi
#
# Run ONCE on each Pi after cloning/copying the repo:
#   cd /home/pi/winddataAPI
#   bash runners/install.sh
#
# What it does:
#   1. Installs Python deps (requests) into a venv
#   2. Writes the crontab entry for this Pi's runner script
#   3. Creates the results and log directories
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

# ── Which Pi am I? (pass as argument, or auto-detect from hostname) ───────────
PI_NUM="${1:-}"
if [ -z "$PI_NUM" ]; then
    HOSTNAME_LOWER=$(hostname | tr '[:upper:]' '[:lower:]')
    if   [[ "$HOSTNAME_LOWER" == *pi1* ]] || [[ "$HOSTNAME_LOWER" == *pi-1* ]]; then PI_NUM=1
    elif [[ "$HOSTNAME_LOWER" == *pi2* ]] || [[ "$HOSTNAME_LOWER" == *pi-2* ]]; then PI_NUM=2
    elif [[ "$HOSTNAME_LOWER" == *pi3* ]] || [[ "$HOSTNAME_LOWER" == *pi-3* ]]; then PI_NUM=3
    else
        echo "Could not auto-detect Pi number from hostname '$(hostname)'."
        echo "Pass it explicitly:  bash runners/install.sh 1"
        exit 1
    fi
fi

RUNNER="$SCRIPT_DIR/pi${PI_NUM}.sh"
if [ ! -f "$RUNNER" ]; then
    echo "Runner script not found: $RUNNER"; exit 1
fi
chmod +x "$RUNNER"

echo "=== Setting up Pi ${PI_NUM} ==="

# ── 1. Create venv and install deps ──────────────────────────────────────────
VENV="$REPO_DIR/.venv"
if [ ! -d "$VENV" ]; then
    echo "Creating Python venv at $VENV …"
    python3 -m venv "$VENV"
fi
echo "Installing Python dependencies …"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet requests

# ── 2. Create output directories ─────────────────────────────────────────────
mkdir -p "$REPO_DIR/crawler/apicrawler/results"
mkdir -p "$REPO_DIR/runners/logs"
echo "Directories ready."

# ── 3. Write the API URL to a .env file if not already set ───────────────────
ENV_FILE="$REPO_DIR/runners/.env"
if [ ! -f "$ENV_FILE" ]; then
    cat > "$ENV_FILE" <<'EOF'
# Set this to your production API base URL.
# It will be sourced by the runner scripts automatically.
WINDDATA_API=https://your-api.onrender.com
# Optional overrides:
# WIND_FARM=kelmarsh
# CRAWL_ITERATIONS=2    # slots per pattern per run (default: 2 for Pi1/2, 1 for Pi3)
# CRAWL_DELAY=180       # seconds between API calls (default: 180 = 3 min)
EOF
    echo "Created $ENV_FILE — edit it and set WINDDATA_API before the first run."
fi

# ── 4. Install crontab entry (runs every 10 minutes) ─────────────────────────
CRON_CMD="*/10 * * * * . $ENV_FILE && bash $RUNNER >> $REPO_DIR/runners/logs/cron_pi${PI_NUM}.log 2>&1"

# Only add if not already present
if crontab -l 2>/dev/null | grep -qF "$RUNNER"; then
    echo "Crontab entry already exists — not modified."
else
    ( crontab -l 2>/dev/null; echo "$CRON_CMD" ) | crontab -
    echo "Crontab entry added:"
    echo "  $CRON_CMD"
fi

echo ""
echo "=== Install complete for Pi ${PI_NUM} ==="
echo ""
echo "Next steps:"
echo "  1. Edit  $ENV_FILE"
echo "     and set WINDDATA_API to your production API URL."
echo "  2. Test manually:"
echo "       . $ENV_FILE && bash $RUNNER"
echo "  3. Cron will fire automatically every 10 minutes."
echo "  4. Results accumulate in:"
echo "       $REPO_DIR/crawler/apicrawler/results/"
echo "  5. Logs:"
echo "       $REPO_DIR/runners/logs/pi${PI_NUM}.log"

