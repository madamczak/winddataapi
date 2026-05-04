# API Crawler — `crawler/apicrawler/`

Randomly samples `(date, hour)` pairs from a wind farm's data range and checks whether **all turbines** in that farm satisfy a named pattern simultaneously. Matching slots are saved to a JSONL file.

## Quick start

```bash
# From the repo root, with the API running locally:
python crawler/apicrawler/crawl.py \
    --api http://localhost:8000 \
    --farm kelmarsh \
    --pattern high_wind_full_spin \
    --iterations 500

# Against a remote API (add delay to be polite):
python crawler/apicrawler/crawl.py \
    --api https://your-api.onrender.com \
    --farm kelmarsh \
    --pattern farm_stopped \
    --iterations 2000 \
    --delay 0.3
```

## All options

| Flag | Default | Description |
|---|---|---|
| `--api URL` | `$WINDDATA_API` or `http://localhost:8000` | API base URL |
| `--farm NAME` | `kelmarsh` | Farm directory name |
| `--pattern NAME` | `high_wind_full_spin` | Which pattern to search for |
| `--iterations N` | `500` | How many random (date, hour) slots to check |
| `--output FILE` | `results/<farm>_<pattern>.jsonl` | Output file (JSONL, one match per line) |
| `--delay SECS` | `0.05` | Pause between API calls |
| `--seed INT` | random | Fix seed for reproducible runs |
| `--verbose` | off | Show rejection reasons for every failed slot |
| `--list-patterns` | — | Print all patterns and exit |

## Available patterns

```
python crawler/apicrawler/crawl.py --list-patterns
```

| Pattern | What it finds |
|---|---|
| `high_wind_full_spin` | All turbines at ~15 RPM, wind ≥ 10 m/s, std < 0.5 RPM |
| `farm_stopped` | All turbines producing < 5 kW and rotor < 1 RPM |
| `rated_power` | All turbines at ≥ 2 000 kW, power std < 50 kW |
| `partial_performance` | All turbines spinning but producing < 800 kW |
| `low_wind_cutin` | Wind 4–7 m/s, rotor 3–10 RPM (cut-in region) |
| `high_nacelle_temp` | Nacelle temperature ≥ 35 °C across all turbines |

## Output format (JSONL)

Each line is a JSON object:

```json
{
  "pattern": "high_wind_full_spin",
  "farm": "kelmarsh",
  "date": "2017-11-03",
  "hour": 14,
  "turbines_matched": ["turbine_1", "turbine_2", "turbine_3", "turbine_4", "turbine_5", "turbine_6"],
  "details_by_turbine": {
    "turbine_1": {
      "Rotor speed (RPM)|mean": 14.983,
      "Rotor speed (RPM)|std": 0.041,
      "Wind speed (m/s)|mean": 12.55
    },
    "turbine_2": { "..." }
  },
  "timestamp_utc": "2026-05-04T10:23:11Z"
}
```

## Running multiple instances

Because output is JSONL (one line per match, appended), you can run several
instances in parallel against the same output file without conflict:

```bash
# Shell 1 — morning hours focus
python crawler/apicrawler/crawl.py --api http://localhost:8000 \
    --farm kelmarsh --pattern high_wind_full_spin --seed 1 &

# Shell 2 — independent random sample
python crawler/apicrawler/crawl.py --api http://localhost:8000 \
    --farm kelmarsh --pattern high_wind_full_spin --seed 2 &
```

## Adding your own patterns

Edit `crawler/apicrawler/patterns.py`. Each entry in `PATTERNS` needs:

```python
"my_pattern": {
    "description": "Human-readable summary",
    "columns": ["Date and time", "Rotor speed (RPM)", "Power (kW)"],
    "min_rows": 3,          # skip hours with fewer readings than this
    "criteria": [
        # ALL criteria must pass for a turbine to match
        {"column": "Rotor speed (RPM)", "agg": "mean", "min": 14.5, "max": 15.5},
        {"column": "Rotor speed (RPM)", "agg": "std",  "min": None, "max": 0.5},
    ],
},
```

`agg` can be:
- `"mean"` — average of the ~6 ten-minute readings in the hour
- `"std"`  — standard deviation of those readings

