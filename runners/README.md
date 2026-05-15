# Raspberry Pi Crawler Runners

Drop this repo on each Pi, run `install.sh` once, and collection starts automatically every 10 minutes via cron.

---

## Files

| File | Purpose |
|---|---|
| `pi1.sh` | Pi 1 — `high_wind_full_spin` + `farm_stopped` |
| `pi2.sh` | Pi 2 — `rated_power` + `partial_performance` |
| `pi3.sh` | Pi 3 — `blade_rpm_15` + `low_wind_cutin` + `high_nacelle_temp` |
| `install.sh` | One-time setup: venv, dirs, crontab, `.env` |
| `.env` | Your API URL (created by `install.sh`, gitignored) |
| `logs/` | Per-Pi log files (created at runtime) |

---

## Updating an existing Pi

```bash
cd ~/winddataAPI
bash runners/update.sh
```

That's it. The script:
1. `git pull` — fetches the latest code from `main`
2. Re-installs/upgrades Python deps in the existing venv
3. Prints the new commit hash
4. Reminds you of any new `.env` variables to set

**No crontab changes needed** — cron already points to the same script paths.

If new env vars were added (e.g. `GRAFANA_LOKI_INSTANCE_ID`), add them to `runners/.env`:
```bash
nano ~/winddataAPI/runners/.env
```

---

## Setup on each Pi (once)

```bash
# 1. Clone or copy the repo
git clone https://github.com/madamczak/winddataapi.git
cd winddataapi

# 2. Run the installer — pass your Pi number (1, 2, or 3)
bash runners/install.sh 1   # on Pi 1
bash runners/install.sh 2   # on Pi 2
bash runners/install.sh 3   # on Pi 3

# 3. Set your API URL
nano runners/.env
#   → change WINDDATA_API=https://your-api.onrender.com

# 4. Test manually before relying on cron
. runners/.env && bash runners/pi1.sh   # (or pi2/pi3)
```

The installer auto-detects the Pi number from hostname if it contains `pi1`/`pi2`/`pi3`. Otherwise pass it as the argument.

---

## What gets installed

**Crontab entry** (every 10 minutes):
```
*/10 * * * * . /path/to/runners/.env && bash /path/to/runners/pi1.sh >> /path/to/runners/logs/cron_pi1.log 2>&1
```

**Python venv** at `.venv/` with `requests` installed.

---

## Timing budget

Each runner fires every 10 minutes. With `CRAWL_DELAY=180` (3 min) between calls:
- Most slots **fail at the first turbine check** → 1 API call + 3 min wait ≈ 3 min per slot
- Rare full match (all 6 turbines pass) → 6 calls + ~18 min total (flock skips the next cron fire safely)

| Pi | Patterns | Iterations/pattern | Worst-case time |
|---|---|---|---|
| **Pi 1** | 2 | 2 | 2 × 2 × 3 min = 12 min\* |
| **Pi 2** | 2 | 2 | 12 min\* |
| **Pi 3** | 3 | 1 | 3 × 3 min = 9 min ✓ |

\* If all slots fail at the first check. Flock prevents overlap if a run runs over.

Override via `.env`:
```bash
CRAWL_ITERATIONS=3   # check more slots per pattern
CRAWL_DELAY=120      # 2-minute gap instead of 3
```

---

## Environment variables

Set these in `runners/.env`:

| Variable | Default | Description |
|---|---|---|
| `WINDDATA_API` | **(required)** | Base URL of the production API |
| `WIND_FARM` | `kelmarsh` | Which farm to crawl |
| `CRAWL_ITERATIONS` | `2` (Pi1/2), `1` (Pi3) | Slots per pattern per run |
| `CRAWL_DELAY` | `180` | Seconds between API calls (3 minutes) |

---

## Results

All three Pis write to `crawler/apicrawler/results/` — one `.jsonl` file per pattern:

```
crawler/apicrawler/results/
  kelmarsh_high_wind_full_spin.jsonl
  kelmarsh_farm_stopped.jsonl
  kelmarsh_rated_power.jsonl
  kelmarsh_partial_performance.jsonl
  kelmarsh_blade_rpm_15.jsonl
  kelmarsh_low_wind_cutin.jsonl
  kelmarsh_high_nacelle_temp.jsonl
```

Each line is one farm-wide match event:
```json
{
  "pattern": "farm_stopped",
  "farm": "kelmarsh",
  "date": "2019-07-23",
  "hour": 4,
  "turbines_matched": ["turbine_1", ..., "turbine_6"],
  "details_by_turbine": { "turbine_1": {"Power (kW)|mean": 0.0}, ... },
  "timestamp_utc": "2026-05-04T19:47:34Z"
}
```

To collect results from all Pis, either:
- Mount a shared NFS/SMB directory and point all Pis at it
- `rsync` from a central machine: `rsync pi@pi1.local:~/winddataapi/crawler/apicrawler/results/ results/`

---

## Pulling results from all Pis

```bash
# From your laptop / central machine:
for i in 1 2 3; do
  rsync -av pi@pi${i}.local:~/winddataapi/crawler/apicrawler/results/ \
            ./collected_results/
done
```

---

## Seed strategy

Each Pi uses a **time-based seed** (`date +%s`) offset by a large prime unique to that Pi:

| Pi | Seed offset |
|---|---|
| Pi 1 | `0` (raw timestamp) |
| Pi 2 | `+2,000,003` |
| Pi 3 | `+4,000,037` |

This ensures the three Pis explore **different random slots** even when they fire at the same moment.

