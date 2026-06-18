# wind_events_crawler — How It Works

## Overview

Each run performs **one task**: call the winddataAPI for a specific farm/turbine/time window,
check whether that data window contains wind speed and power readings, record a "finding" if it
does, and **commit + push that finding to the shared git repo**.  
Multiple Raspberry Pis can run it independently — git is the shared result store.

---

## Execution flow

```
startup
  │
  ├─ 1. LOCK — create a .lock file beside the result JSON.
  │           If another process holds it → skip this run.
  │           If lock is stale (dead PID + older than STALE_LOCK_TIMEOUT_S) → recover it.
  │
  ├─ 2. UPDATE — git fetch + fast-forward pull from origin/main.
  │           If new code was pulled → exec() replaces the process with the updated version
  │           and continues the same run_id (self-updating worker).
  │
  ├─ 3. API CALL — HTTP GET to:
  │     {WINDDATA_API}/farms/{SCENARIO_FARM}/data/turbines/{SCENARIO_TURBINE}/query
  │                  ?start={SCENARIO_WINDOW_START_UTC}&end={SCENARIO_WINDOW_END_UTC}
  │           Retries with exponential back-off on 408/429/5xx and network errors.
  │
  ├─ 4. SCENARIO — "data_presence" check:
  │           Does the response have any rows with a non-null "Wind speed (m/s)"
  │           AND "Power (kW)"? If yes → one Finding is produced.
  │
  ├─ 5. PERSIST — merge findings into the local JSON artifact
  │     (crawler/output/wind_events_crawler/wind_events_crawler.json).
  │
  ├─ 6. PUBLISH — git fetch → reset local branch → re-persist → commit → push.
  │           On non-fast-forward conflict: retry once, then fail.
  │
  └─ 7. RELEASE lock → log run_completed.
```

Every stage emits a structured JSON log line (to stdout + Grafana Loki).

---

## Environment variables

### ✅ Required

| Variable | Example | What it does |
|---|---|---|
| `WINDDATA_API` | `https://winddataapi-backend.onrender.com` | Base URL of the API — no trailing slash |
| `PI_ID` | `pi1` | Identifies this machine in logs, lock files and git commits |
| `SCENARIO_FARM` | `kelmarsh` | Which farm to query |
| `SCENARIO_TURBINE` | `turbine_2` | Which turbine table within that farm |
| `SCENARIO_WINDOW_START_UTC` | `2018-05-30T20:00:00Z` | Start of the data window (ISO 8601 UTC) |
| `SCENARIO_WINDOW_END_UTC` | `2018-05-30T22:00:00Z` | End of the data window — must be after start |

### ⚙️ Optional — git

| Variable | Default | What it does |
|---|---|---|
| `GIT_REMOTE_NAME` | `origin` | Remote to fetch/push findings to |
| `GIT_BRANCH` | `main` | Branch to sync and publish on |

### ⚙️ Optional — API behaviour

| Variable | Default | What it does |
|---|---|---|
| `REQUEST_DELAY_S` | `2.0` | Minimum seconds between API requests |
| `API_MAX_RETRIES` | `3` | Max retry attempts on transient errors |
| `API_BACKOFF_BASE_S` | `1.0` | Base for exponential back-off (seconds) |
| `API_BACKOFF_JITTER_S` | `0.25` | Random jitter added on top of back-off |

### ⚙️ Optional — reliability

| Variable | Default | What it does |
|---|---|---|
| `STALE_LOCK_TIMEOUT_S` | `1800` | Seconds after which a lock from a dead process can be recovered |
| `WIND_EVENTS_RESULT_PATH` | `crawler/output/wind_events_crawler/wind_events_crawler.json` | Override where the result artifact is written |

### ⚙️ Optional — Grafana telemetry

| Variable | Default | What it does |
|---|---|---|
| `ENVIRONMENT` | `production` | Loki `env` label — set to `local` for dev |
| `GRAFANA_LOKI_URL` | `https://logs-prod-025.grafana.net/loki/api/v1/push` | Loki push endpoint |
| `GRAFANA_LOKI_INSTANCE_ID` | _(none)_ | Your Loki instance ID (`1380423`) |
| `GRAFANA_TOKEN` | _(none)_ | Grafana Access Policy token |

Without `GRAFANA_LOKI_INSTANCE_ID` + `GRAFANA_TOKEN` the worker still runs — logs just go to stdout only.

---

## Running on a Raspberry Pi

### 1. First-time setup

```bash
# Clone the repo (once)
cd /home/pi
git clone https://github.com/adamczakmateusz/winddataAPI.git
cd winddataAPI

# Install uv (the package manager the worker uses)
curl -Lsf https://astral.sh/uv/install.sh | sh

# Install worker dependencies
uv sync --directory crawler/wind_events_crawler
```

### 2. Create the `.env` file

```bash
cp runners/wind_events_crawler/.env.example runners/wind_events_crawler/.env
nano runners/wind_events_crawler/.env
```

Minimum required content:

```bash
WINDDATA_API=https://winddataapi-backend.onrender.com
PI_ID=pi1

SCENARIO_FARM=kelmarsh
SCENARIO_TURBINE=turbine_2
SCENARIO_WINDOW_START_UTC=2018-05-30T20:00:00Z
SCENARIO_WINDOW_END_UTC=2018-05-30T22:00:00Z

# Optional — for Grafana logs
GRAFANA_LOKI_INSTANCE_ID=1380423
GRAFANA_TOKEN=glc_eyJ...
```

### 3. Run once manually to test

```bash
cd /home/pi/winddataAPI
bash runners/wind_events_crawler/run.sh
```

You should see JSON log lines on stdout ending with `"event":"run_completed"`.

### 4. Schedule with cron (every 10 minutes)

```bash
crontab -e
```

Add:

```cron
*/10 * * * * cd /home/pi/winddataAPI && /usr/bin/env bash runners/wind_events_crawler/run.sh >> runners/wind_events_crawler/cron.log 2>&1
```

### 5. Enable passwordless git push

The worker pushes findings automatically — the Pi needs passwordless git access:

```bash
# Generate a key if you don't have one
ssh-keygen -t ed25519 -C "pi1@winddataAPI"

# Add the public key to GitHub
cat ~/.ssh/id_ed25519.pub
# → paste into GitHub → Settings → SSH keys

# Switch the repo remote to SSH
cd /home/pi/winddataAPI
git remote set-url origin git@github.com:adamczakmateusz/winddataAPI.git
```

---

## Output artifact

After each successful run, `crawler/output/wind_events_crawler/wind_events_crawler.json` is
updated and pushed to the shared repo. Example:

```json
{
  "schema_version": "0.1.0",
  "generated_at_utc": "2026-06-18T10:00:00Z",
  "producer": {
    "worker": "wind_events_crawler",
    "pi_id": "pi1",
    "revision": "abc123def456"
  },
  "findings": [
    {
      "scenario": "data_presence",
      "farm": "kelmarsh",
      "turbine": "turbine_2",
      "evaluated_window_start_utc": "2018-05-30T20:00:00Z",
      "evaluated_window_end_utc": "2018-05-30T22:00:00Z"
    }
  ]
}
```

A **finding** means: data was present in the queried window (both wind speed and power readings
were non-null). No finding means the window returned empty or null data.

---

## Source layout

```
crawler/wind_events_crawler/
  src/wind_events_crawler/
    cli.py              — entrypoint (calls initialize_worker)
    run_worker.py       — orchestrates all 7 stages
    config.py           — reads + validates all env vars → WorkerConfig
    api_client.py       — HTTP client with retry / back-off / rate limiting
    scenario_runner.py  — "data_presence" scenario evaluation logic
    locking.py          — file-based distributed lock
    updater.py          — git fetch / pull / commit / push
    result_repository.py— JSON artifact read / merge / write
    models.py           — shared dataclasses (Finding, ResultArtifact, …)
    telemetry.py        — structured JSON logging + Loki push
    exceptions.py       — typed exception hierarchy
  pyproject.toml        — uv package definition
runners/wind_events_crawler/
  run.sh                — thin bash wrapper (loads .env, calls uv run)
  .env.example          — template for the .env file
  cron_example.txt      — ready-to-paste crontab line
```

