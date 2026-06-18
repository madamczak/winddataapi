"""
fabfile.py — Fleet management for the winddataAPI Raspberry Pi fleet.

Usage (from repo root):
    fab setup          # first-time full setup on all Pis
    fab deploy         # git pull + uv sync on all Pis
    fab push-envs      # upload each Pi's .env file
    fab setup-cron     # install wind_events_crawler cron job (removes old entries first)
    fab remove-cron    # remove wind_events_crawler cron job from all Pis
    fab status         # git HEAD + last log line on each Pi
    fab logs           # tail last 30 lines of cron log on each Pi
    fab collect-logs   # download all cron logs to logs/ on your PC
    fab run-now        # trigger the crawler immediately on all Pis

Single-Pi targeting:
    fab -H pi@192.168.0.103 deploy
    fab -H pi@192.168.0.103 logs

Requirements:
    pip install fabric
"""

from __future__ import annotations

import os
from fabric import Connection, SerialGroup, task

# ── Fleet definition ──────────────────────────────────────────────────────────

PIES: dict[str, str] = {
    "pi1": "pi@192.168.0.103",
    "pi2": "pi@192.168.0.105",
    "pi3": "pi@192.168.0.108",
}

WORK_DIR    = "/home/pi/Programming"
REPO        = f"{WORK_DIR}/winddataAPI"
RUNNER_DIR  = f"{REPO}/runners/wind_events_crawler"
RUNNER      = f"{RUNNER_DIR}/run.sh"
CRON_LOG    = f"{RUNNER_DIR}/cron.log"
ENV_DEST    = f"{RUNNER_DIR}/.env"
OUTPUT_DIR  = f"{REPO}/crawler/output/wind_events_crawler"

# Cron line installed by setup-cron / removed by remove-cron
CRON_TAG    = "wind_events_crawler"
CRON_LINE   = (
    f"*/10 * * * * cd {REPO} && "
    f"/usr/bin/env bash {RUNNER} >> {CRON_LOG} 2>&1"
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _connections() -> list[Connection]:
    return [Connection(host) for host in PIES.values()]


def _run_all(command: str, *, warn: bool = False) -> None:
    """Run command on all Pis in parallel, print labelled output."""
    for pi_id, host in PIES.items():
        print(f"\n{'─'*60}")
        print(f"  {pi_id}  ({host})")
        print(f"{'─'*60}")
        c = Connection(host)
        c.run(command, warn=warn)


def _header(title: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

# ── Tasks ─────────────────────────────────────────────────────────────────────

@task
def setup(c):
    """
    Full first-time setup on all Pis:
      1. Ensure ~/Programming working directory exists
      2. Clone repo (or pull latest if already cloned)
      3. Install uv
      4. Sync wind_events_crawler dependencies
      5. Create output directory
      6. Push Pi-specific .env file
      7. Install cron job
    """
    _header("SETUP — all Pis")
    for pi_id, host in PIES.items():
        print(f"\n>>> {pi_id}  ({host})")
        conn = Connection(host)

        # 1. Ensure working directory exists
        conn.run(f"mkdir -p {WORK_DIR}")

        # 2. Clone repo if missing, otherwise pull latest
        conn.run(
            f"if [ -d {REPO}/.git ]; then "
            f"  echo 'repo exists — pulling latest' && cd {REPO} && git pull; "
            f"elif [ -d {REPO} ]; then "
            f"  echo 'directory exists but not a git repo — removing and cloning' && "
            f"  rm -rf {REPO} && git clone https://github.com/madamczak/winddataapi.git {REPO}; "
            f"else "
            f"  echo 'cloning repo' && git clone https://github.com/madamczak/winddataapi.git {REPO}; "
            f"fi"
        )

        # 3. Install uv if missing
        conn.run(
            "command -v uv >/dev/null 2>&1 && echo 'uv ok' || "
            "curl -LsSf https://astral.sh/uv/install.sh | sh"
        )

        # 4. Sync worker dependencies
        conn.run(f"cd {REPO} && $HOME/.local/bin/uv sync --directory crawler/wind_events_crawler")

        # 5. Create output directory
        conn.run(f"mkdir -p {OUTPUT_DIR}")

        # 6. Push .env
        local_env = f"runners/wind_events_crawler/.env.{pi_id}"
        if os.path.exists(local_env):
            conn.put(local_env, ENV_DEST)
            conn.run(f"sed -i 's/\\r//' {ENV_DEST}")   # strip Windows CRLF
            print(f"  .env pushed from {local_env}")
        else:
            print(f"  WARNING: {local_env} not found — skipping .env upload")

        # 7. Switch remote to SSH so the worker can push findings
        conn.run(f"cd {REPO} && git remote set-url origin git@github.com:madamczak/winddataapi.git")

        # 8. Cron
        _install_cron(conn, pi_id)

    _header("SETUP COMPLETE")


@task
def deploy(c):
    """Pull latest code and sync uv deps on all Pis."""
    _header("DEPLOY — git pull + uv sync")
    _run_all(
        f"cd {REPO} && git pull && "
        f"$HOME/.local/bin/uv sync --directory crawler/wind_events_crawler"
    )


@task
def push_envs(c):
    """Upload each Pi's .env file to the correct Pi."""
    _header("PUSH ENV FILES")
    for pi_id, host in PIES.items():
        local_env = f"runners/wind_events_crawler/.env.{pi_id}"
        if not os.path.exists(local_env):
            print(f"  {pi_id}: SKIP — {local_env} not found")
            continue
        conn = Connection(host)
        conn.put(local_env, ENV_DEST)
        conn.run(f"sed -i 's/\\r//' {ENV_DEST}")   # strip Windows CRLF
        print(f"  {pi_id} ({host}): pushed {local_env} → {ENV_DEST}")


@task
def setup_cron(c):
    """
    Install the wind_events_crawler cron job on all Pis.
    Removes any existing entry containing 'wind_events_crawler' first.
    """
    _header("SETUP CRON")
    for pi_id, host in PIES.items():
        print(f"\n>>> {pi_id}  ({host})")
        conn = Connection(host)
        _install_cron(conn, pi_id)


@task
def remove_cron(c):
    """Remove the wind_events_crawler cron job from all Pis."""
    _header("REMOVE CRON")
    for pi_id, host in PIES.items():
        print(f"\n>>> {pi_id}  ({host})")
        conn = Connection(host)
        _remove_cron(conn)
        print(f"  {pi_id}: cron entry removed (if it existed)")


@task
def status(c):
    """Show git HEAD and last cron log line on each Pi."""
    _header("STATUS")
    _run_all(
        f"echo '--- git ---' && cd {REPO} && git log --oneline -1 && "
        f"echo '--- last log ---' && tail -1 {CRON_LOG} 2>/dev/null || echo '(no log yet)'",
        warn=True
    )


@task
def logs(c):
    """Tail last 30 lines of the cron log on each Pi."""
    _header("LOGS")
    _run_all(f"tail -30 {CRON_LOG} 2>/dev/null || echo '(no log yet)'", warn=True)


@task
def collect_logs(c):
    """Download cron logs from all Pis into logs/ on your PC."""
    _header("COLLECT LOGS")
    os.makedirs("logs", exist_ok=True)
    for pi_id, host in PIES.items():
        dest = f"logs/{pi_id}_cron.log"
        try:
            Connection(host).get(CRON_LOG, dest)
            print(f"  {pi_id}: downloaded → {dest}")
        except Exception as e:
            print(f"  {pi_id}: SKIP — {e}")


@task
def run_now(c):
    """Trigger the wind_events_crawler immediately on all Pis (outside cron)."""
    _header("RUN NOW")
    _run_all(f"bash {RUNNER}", warn=True)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _remove_cron(conn: Connection) -> None:
    """Strip any crontab line containing CRON_TAG."""
    conn.run(
        f"(crontab -l 2>/dev/null | grep -v '{CRON_TAG}') | crontab -",
        warn=True
    )


def _install_cron(conn: Connection, pi_id: str) -> None:
    """Remove existing entry then add the fresh one."""
    _remove_cron(conn)
    conn.run(f'(crontab -l 2>/dev/null; echo "{CRON_LINE}") | crontab -')
    print(f"  {pi_id}: cron installed → {CRON_LINE}")
