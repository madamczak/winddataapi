#!/usr/bin/env bash
# =============================================================================
# update.sh — pull the latest crawler code onto a Raspberry Pi
#
# Run from the repo root:
#   bash runners/update.sh
#
# What it does:
#   1. git pull (fetch + merge latest main)
#   2. Re-installs/updates Python deps in the venv
#   3. Prints the new version and reminder to check .env for new variables
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
VENV="$REPO_DIR/.venv"

echo "=== Updating winddataAPI on $(hostname) ==="
echo ""

# ── 1. Pull latest code ───────────────────────────────────────────────────────
cd "$REPO_DIR"
echo "→ git pull …"
git pull --ff-only origin main
echo ""

# ── 2. Update Python deps ─────────────────────────────────────────────────────
if [ -d "$VENV" ]; then
    echo "→ Updating Python dependencies …"
    "$VENV/bin/pip" install --quiet --upgrade pip

    # apicrawler only needs requests
    "$VENV/bin/pip" install --quiet requests
    echo "   Dependencies up to date."
else
    echo "WARNING: .venv not found — run  bash runners/install.sh  first."
fi

echo ""

# ── 3. Show new commit ────────────────────────────────────────────────────────
echo "→ Now at commit: $(git log -1 --oneline)"
echo ""

# ── 4. Remind about .env ─────────────────────────────────────────────────────
ENV_FILE="$SCRIPT_DIR/.env"
echo "─────────────────────────────────────────────────"
echo "Reminder: check $ENV_FILE for any new variables."
echo "Current contents:"
echo ""
cat "$ENV_FILE" 2>/dev/null || echo "  (file not found — run install.sh first)"
echo ""
echo "─────────────────────────────────────────────────"
echo "New env vars added in this version:"
echo "  GRAFANA_LOKI_INSTANCE_ID  — Loki tenant ID (optional, enables crawler logs in Grafana)"
echo "  GRAFANA_TOKEN             — Grafana Access Policy token"
echo "  PI_ID                     — e.g. pi1 / pi2 / pi3 (labels logs)"
echo "─────────────────────────────────────────────────"
echo ""
echo "=== Update complete ==="
echo "Cron will pick up the new code on the next 10-minute tick."
echo "To test immediately: . $ENV_FILE && bash $SCRIPT_DIR/pi\$(hostname | grep -oE '[123]' | head -1).sh"

