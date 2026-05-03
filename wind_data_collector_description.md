# Wind Turbine Hourly Data Collector — Program Description

## Purpose

A Python script that systematically queries a wind farm API for one hour of turbine data at a time, enriches each hourly snapshot with its corresponding operational status events, computes per-hour statistical summaries, and persists everything to structured JSON files for further analysis or LLM-based reasoning.

The script is designed as a **one-shot batch process** — it starts, does its work, saves the output, and exits cleanly. There is no daemon, scheduler, or persistent state. Once the process finishes it has fulfilled its purpose and terminates.

---

## Execution Model

### One-time batch process

The script follows a strict **run-to-completion** lifecycle:

```
START
  │
  ├─ Load config (columns.json, CLI args)
  ├─ Validate API reachability (single health-check request)
  │
  ├─ for each farm / turbine / hour  →  query → enrich → summarise
  │
  ├─ Write all output files to disk
  ├─ Print final run summary (farms processed, hours collected, errors)
  │
EXIT (code 0 on success, non-zero on fatal error)
```

There is **no background thread, no loop, no scheduler**. The OS process starts, does exactly one pass over the requested data range, flushes everything to storage, and exits. It can be triggered by:

- Running manually from a terminal
- A cron job / Task Scheduler entry
- A CI/CD pipeline step
- Any orchestrator (Airflow, Prefect, GitHub Actions, etc.) that treats it as a single task

### Process exit codes

| Code | Meaning |
|------|---------|
| `0` | All data collected and saved successfully |
| `1` | Fatal error (API unreachable, bad config, I/O failure) |
| `2` | Partial success — some hours had fetch errors (logged, skipped) |

### Storage back-end (pluggable)

Output is written through a thin **storage adapter** so the destination can be swapped without touching collection logic:

| Phase | Back-end | Notes |
|-------|----------|-------|
| **Now** | Local disk | Files written to `output/` directory |
| **Later** | AWS S3 | `boto3` — drop-in swap via `--storage s3 --bucket my-bucket` |
| **Later** | Cloudflare R2 | R2 is S3-compatible; same `boto3` adapter with a custom endpoint URL |

The adapter interface is simple:

```python
class StorageAdapter:
    def write(self, key: str, data: str) -> None:
        """key = relative file path, data = JSON string"""
        ...
```

Concrete implementations:

```python
# Local disk (default)
class LocalStorage(StorageAdapter):
    def write(self, key, data):
        path = Path(self.output_dir) / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data, encoding="utf-8")

# S3 / R2 (future)
class S3Storage(StorageAdapter):
    def write(self, key, data):
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data)
```

The adapter is selected at startup based on the `--storage` flag (`local` by default) and is passed into the collection pipeline — no other code needs to change when the destination switches.

### CLI flags for storage

```bash
# Write to local disk (default)
python collect_hourly.py --farm kelmarsh --turbine turbine_2 \
    --start "2018-01-01 00:00:00" --end "2018-12-31 23:59:59"

# Write to S3
python collect_hourly.py --farm kelmarsh --turbine turbine_2 \
    --start "2018-01-01 00:00:00" --end "2018-12-31 23:59:59" \
    --storage s3 --bucket my-wind-data-bucket --prefix kelmarsh/2018/

# Write to Cloudflare R2
python collect_hourly.py --farm kelmarsh --turbine turbine_2 \
    --start "2018-01-01 00:00:00" --end "2018-12-31 23:59:59" \
    --storage r2 --bucket my-r2-bucket --endpoint https://<account>.r2.cloudflarestorage.com
```

### Final run summary printed on exit

```
====================================================
  Wind Turbine Data Collector — Run Complete
====================================================
  Farm(s)       : kelmarsh
  Turbine(s)    : turbine_2
  Period        : 2018-01-01 00:00  →  2018-12-31 23:59
  Hours total   : 8760
  Hours OK      : 8731
  Hours missing : 18    (data_missing=true)
  Fetch errors  : 11    (fetch_error=true, see run.log)
  Files written : 2     (raw + summary)
  Storage       : local  →  output/
  Duration      : 4m 22s
====================================================
```

---

## Scope

| Dimension | Details |
|-----------|---------|
| **Farms** | `kelmarsh`, `penmanshiel` |
| **Data types** | `data` (sensor readings), `status` (operational events) |
| **Turbines** | All turbines available per farm (e.g. `turbine_1` … `turbine_N`) |
| **Time resolution** | One calendar hour per iteration |
| **Expected data points per hour** | 5 (one every 10 minutes) |
| **API base** | `http://192.168.0.103:8000` |
| **Endpoint pattern** | `/farms/{farm}/{data_type}/turbines/{turbine}/query` |
| **Query parameters** | `start` and `end` as `YYYY-MM-DD HH:MM:SS` strings |
| **Weather API** | OpenWeatherMap History API (`api.openweathermap.org/data/3.0/onecall/timemachine`) |
| **Weather resolution** | One call per farm per hour (shared across all turbines at the same farm) |

---

## High-Level Flow

```
for each farm:
    determine date range (min datetime → max datetime from the database)
    for each calendar hour in the date range:
        3b. Fetch WEATHER from OpenWeatherMap for this farm + hour   ← shared across all turbines
        for each turbine in the farm:
            1. Query DATA   for [hour_start, hour_end]
            2. Query STATUS for [hour_start, hour_end]
            3. Attach weather snapshot to the hourly record
            4. Compute statistical summary (mean + std dev per numeric column)
            5. Append record   → raw_data.json
            6. Append summary  → summary_data.json
```

---

## Detailed Step Descriptions

### Step 1 — Determine the Date Range

- The script accepts an optional `--start` and `--end` CLI argument (ISO date strings).
- If omitted, it falls back to hardcoded sensible defaults per farm (e.g. the earliest and latest known timestamps in the dataset).
- The range is then broken into a list of hourly windows:
  ```
  windows = [(hour_start, hour_end), ...]   # hour_end = hour_start + 59 min 59 sec
  ```

### Step 1b — Configure Columns to Collect

Not all ~325 data columns need to be saved for every use case. The script supports a **column configuration file** (`columns.json`) that lists exactly which columns to keep. If the file is absent, **all columns are saved** (default behaviour).

#### `columns.json` format

```json
{
  "data": [
    "Date and time",
    "Wind speed (m/s)",
    "Wind speed, Standard deviation (m/s)",
    "Wind speed, Minimum (m/s)",
    "Wind speed, Maximum (m/s)",
    "Density adjusted wind speed (m/s)",
    "Wind direction (°)",
    "Nacelle position (°)",
    "Power (kW)",
    "Power, Standard deviation (kW)",
    "Power, Minimum (kW)",
    "Power, Maximum (kW)",
    "Rotor speed (RPM)",
    "Generator RPM (RPM)",
    "Blade angle (pitch position) A (°)",
    "Blade angle (pitch position) B (°)",
    "Blade angle (pitch position) C (°)",
    "Nacelle ambient temperature (°C)",
    "Nacelle temperature (°C)",
    "Gear oil temperature (°C)",
    "Generator bearing front temperature (°C)",
    "Generator bearing rear temperature (°C)",
    "Front bearing temperature (°C)",
    "Rear bearing temperature (°C)",
    "Stator temperature 1 (°C)",
    "Grid voltage (V)",
    "Grid current (A)",
    "Grid frequency (Hz)",
    "Reactive power (kvar)",
    "Power factor (cosphi)",
    "Energy Export (kWh)",
    "Drive train acceleration (mm/s²)",
    "Tower Acceleration X (mm/s²)",
    "Tower Acceleration Y (mm/s²)",
    "Capacity factor",
    "Data Availability"
  ],
  "status": [
    "Timestamp start",
    "Timestamp end",
    "Duration",
    "Status",
    "Code",
    "Message",
    "IEC category"
  ]
}
```

> **Tip — suggested column sets:**
>
> | Use case | Recommended columns to keep |
> |----------|-----------------------------|
> | **Power performance** | `Date and time`, `Wind speed`, `Density adjusted wind speed`, `Power`, `Rotor speed`, `Blade angle A/B/C`, `Capacity factor` |
> | **Thermal health** | `Date and time`, all `*temperature*` columns, `Gear oil temperature`, `Gear oil inlet temperature` |
> | **Electrical quality** | `Date and time`, `Grid voltage`, `Grid current`, `Grid frequency`, `Power factor`, `Reactive power`, `Apparent power` |
> | **Vibration / structural** | `Date and time`, `Drive train acceleration`, `Tower Acceleration X`, `Tower Acceleration Y` |
> | **Availability analysis** | `Date and time`, `Energy Export`, `Lost Production Total`, `Time-based Contractual Avail.`, `Data Availability` |

#### How column filtering is applied

- After the API response is received the script drops any key in each row that is **not** listed in `columns.json["data"]`.
- `Date and time` is always retained regardless of the config (it is the row identifier).
- The statistical summary in Step 5 is computed **only over the retained columns**, keeping the summary file small and focused.
- A `--columns` CLI flag can point to a custom config path instead of the default `columns.json`:
  ```bash
  python collect_hourly.py --farm kelmarsh --turbine turbine_2 \
      --start "2018-05-30 00:00:00" --end "2018-05-30 23:59:59" \
      --columns configs/thermal_columns.json
  ```

### Step 2 — Query DATA for One Hour

- HTTP GET to:
  ```
  /farms/{farm}/data/turbines/{turbine}/query?start=...&end=...
  ```
- The response JSON has the shape:
  ```json
  {
    "farm": "kelmarsh",
    "data_type": "data",
    "turbine": "turbine_2",
    "count": 5,
    "rows": [ { "Date and time": "...", "Wind speed (m/s)": 7.3, ... }, ... ]
  }
  ```
- All 5 rows (one per 10-minute interval) are stored as-is under the `data_points` key of the hourly record.
- If `count == 0` the hour is still recorded with an empty list and flagged as `data_missing: true`.

### Step 3 — Query STATUS for the Same Hour

- HTTP GET to:
  ```
  /farms/{farm}/status/turbines/{turbine}/query?start=...&end=...
  ```
- Response shape is identical but rows contain status/event fields (e.g. status code, description, duration).
- **Zero or many** status rows may be returned for a given hour.
- All status rows are stored in a `statuses` list inside the hourly record.
- If the list is empty it means the turbine operated normally during that hour (no reported events).

### Step 3b — Fetch Weather from OpenWeatherMap

For every farm, **one weather request is made per calendar hour** and the result is reused for all turbines at that farm. This avoids redundant API calls since all turbines at a site share the same ambient conditions.

#### API used

OpenWeatherMap **One Call API 3.0 — Time Machine** (historical data):

```
GET https://api.openweathermap.org/data/3.0/onecall/timemachine
    ?lat={lat}&lon={lon}&dt={unix_timestamp}&appid={API_KEY}&units=metric
```

- `lat` / `lon` — geographic coordinates of the wind farm (stored in a `farms.json` config file, see below)
- `dt` — Unix timestamp for `hour_start`
- `units=metric` — all values returned in SI / metric units

#### Farm coordinates config — `farms.json`

```json
{
  "kelmarsh": {
    "lat": 52.3838,
    "lon": -1.0866
  },
  "penmanshiel": {
    "lat": 55.9130,
    "lon": -2.2730
  }
}
```

#### Fields extracted from the OWM response

| OWM field | Unit | Description |
|-----------|------|-------------|
| `dt` | Unix ts | Timestamp of the weather observation |
| `temp` | °C | Air temperature at 2 m |
| `feels_like` | °C | Apparent ("feels like") temperature |
| `pressure` | hPa | Atmospheric pressure at sea level |
| `humidity` | % | Relative humidity |
| `dew_point` | °C | Dew point temperature |
| `clouds` | % | Cloud cover percentage |
| `visibility` | m | Visibility distance |
| `wind_speed` | m/s | Wind speed at 10 m (OWM reference height) |
| `wind_deg` | degrees | Wind direction (meteorological) |
| `wind_gust` | m/s | Wind gust speed (if available) |
| `weather[0].main` | string | Short weather condition label (e.g. `"Rain"`, `"Clear"`) |
| `weather[0].description` | string | Detailed condition (e.g. `"light intensity drizzle"`) |
| `rain.1h` | mm | Rainfall in the past hour (if present) |
| `snow.1h` | mm | Snowfall in the past hour (if present) |
| `uvi` | — | UV index |

#### How weather data is attached to the hourly record

The weather snapshot is stored under a `weather` key at the top level of the hourly record, **alongside** `data_points` and `statuses`. It is farm-level data, not turbine-specific:

```json
{
  "farm": "kelmarsh",
  "turbine": "turbine_2",
  "hour_start": "2018-05-30 20:00:00",
  "hour_end": "2018-05-30 20:59:59",
  "data_missing": false,
  "weather": {
    "source": "openweathermap",
    "temp": 11.2,
    "feels_like": 9.7,
    "pressure": 1013,
    "humidity": 72,
    "dew_point": 6.3,
    "clouds": 40,
    "visibility": 10000,
    "wind_speed": 7.4,
    "wind_deg": 218,
    "wind_gust": 10.1,
    "condition": "Clouds",
    "condition_detail": "scattered clouds",
    "rain_1h": 0.0,
    "snow_1h": 0.0,
    "uvi": 0.0,
    "weather_missing": false
  },
  "data_points": [ "..." ],
  "statuses": [ "..." ]
}
```

If the OWM request fails, `weather_missing` is set to `true` and all other weather fields are `null` — the hour record is still saved.

#### API key configuration

The OWM API key is **never hard-coded**. It is read from:

1. The environment variable `OWM_API_KEY` (preferred for CI/CD and production)
2. A `.env` file in the project root (for local development, loaded via `python-dotenv`)

```bash
# .env
OWM_API_KEY=your_openweathermap_api_key_here
```

#### Rate limiting and caching

- The One Call 3.0 free tier allows **1 000 calls/day**. For large date ranges this can be exceeded quickly.
- Weather results are **cached in memory** within a single run: if two turbines at the same farm share the same hour, only one OWM call is made.
- For multi-day runs the script optionally writes a `weather_cache.json` to disk so re-runs over the same period do not re-fetch already retrieved hours (`--cache-weather` flag).

#### Required extra dependency

```
python-dotenv
```

Added to `requirements.txt` alongside `httpx` and `tqdm`.

---

### Step 4 — Build the Hourly Record

Each hourly record is a self-contained JSON object. Below is a full example showing **all available columns**:

#### Data columns — field reference

| Column | Unit | Description |
|--------|------|-------------|
| `Date and time` | ISO datetime | Timestamp of the 10-minute sample |
| `Wind speed (m/s)` | m/s | Mean wind speed over the 10-min interval |
| `Wind speed, Standard deviation (m/s)` | m/s | Std dev of wind speed within the interval |
| `Wind speed, Minimum (m/s)` | m/s | Minimum wind speed recorded |
| `Wind speed, Maximum (m/s)` | m/s | Maximum wind speed recorded |
| `Long Term Wind (m/s)` | m/s | Long-term reference wind speed at the site |
| `Wind speed Sensor 1 (m/s)` | m/s | Reading from primary anemometer (sensor 1) |
| `Wind speed Sensor 1, Standard deviation (m/s)` | m/s | Std dev from sensor 1 |
| `Wind speed Sensor 1, Minimum (m/s)` | m/s | Minimum from sensor 1 |
| `Wind speed Sensor 1, Maximum (m/s)` | m/s | Maximum from sensor 1 |
| `Wind speed Sensor 2 (m/s)` | m/s | Reading from secondary anemometer (sensor 2) |
| `Wind speed Sensor 2, Standard deviation (m/s)` | m/s | Std dev from sensor 2 |
| `Wind speed Sensor 2, Minimum (m/s)` | m/s | Minimum from sensor 2 |
| `Wind speed Sensor 2, Maximum (m/s)` | m/s | Maximum from sensor 2 |
| `Density adjusted wind speed (m/s)` | m/s | Wind speed corrected for air density |
| `Wind direction (°)` | degrees | Mean wind direction (meteorological convention) |
| `Wind direction, Standard deviation (°)` | degrees | Variability in wind direction |
| `Wind direction, Minimum (°)` | degrees | Minimum wind direction recorded |
| `Wind direction, Maximum (°)` | degrees | Maximum wind direction recorded |
| `Nacelle position (°)` | degrees | Compass heading the nacelle is pointing |
| `Nacelle position, Standard deviation (°)` | degrees | Std dev of nacelle heading |
| `Nacelle position, Minimum (°)` | degrees | Minimum nacelle heading |
| `Nacelle position, Maximum (°)` | degrees | Maximum nacelle heading |
| `Vane position 1+2 (°)` | degrees | Combined wind vane reading (vanes 1 and 2) |
| `Vane position 1+2, Max (°)` | degrees | Maximum vane position |
| `Vane position 1+2, Min (°)` | degrees | Minimum vane position |
| `Vane position 1+2, StdDev (°)` | degrees | Std dev of vane position |
| `Power (kW)` | kW | Mean electrical power output |
| `Power, Standard deviation (kW)` | kW | Variability in power output |
| `Power, Minimum (kW)` | kW | Minimum power output |
| `Power, Maximum (kW)` | kW | Maximum power output |
| `Potential power default PC (kW)` | kW | Theoretical power from default power curve |
| `Potential power learned PC (kW)` | kW | Theoretical power from site-learned power curve |
| `Potential power reference turbines (kW)` | kW | Potential power derived from reference turbines |
| `Potential power met mast anemometer (kW)` | kW | Potential power using met-mast wind speed |
| `Potential power estimated (kW)` | kW | Estimated potential power |
| `Cascading potential power (kW)` | kW | Cascading calculation of potential power |
| `Cascading potential power for performance (kW)` | kW | Cascading potential power used for performance KPIs |
| `Available Capacity for Production (kW)` | kW | Turbine capacity available to generate |
| `Available Capacity for Production (Planned) (kW)` | kW | Planned available capacity |
| `Manufacturer Potential Power (SCADA) (kW)` | kW | OEM-reported potential power from SCADA |
| `Turbine Power setpoint (kW)` | kW | Active power setpoint commanded to the turbine |
| `Turbine Power setpoint, Max (kW)` | kW | Maximum setpoint during interval |
| `Turbine Power setpoint, Min (kW)` | kW | Minimum setpoint during interval |
| `Turbine Power setpoint, StdDev (kW)` | kW | Std dev of setpoint |
| `Power factor (cosphi)` | — | Power factor (ratio of real to apparent power) |
| `Power factor (cosphi), Max` | — | Maximum power factor |
| `Power factor (cosphi), Min` | — | Minimum power factor |
| `Power factor (cosphi), Standard deviation` | — | Std dev of power factor |
| `Reactive power (kvar)` | kvar | Mean reactive power |
| `Reactive power, Max (kvar)` | kvar | Maximum reactive power |
| `Reactive power, Min (kvar)` | kvar | Minimum reactive power |
| `Reactive power, Standard deviation (kvar)` | kvar | Std dev of reactive power |
| `Apparent power (kVA)` | kVA | Mean apparent power |
| `Apparent power, Max (kVA)` | kVA | Maximum apparent power |
| `Apparent power, Min (kVA)` | kVA | Minimum apparent power |
| `Apparent power, StdDev (kVA)` | kVA | Std dev of apparent power |
| `Energy Export (kWh)` | kWh | Energy exported to grid in this interval |
| `Energy Export counter (kWh)` | kWh | Cumulative energy export meter reading |
| `Energy Import (kWh)` | kWh | Energy imported from grid (auxiliary consumption) |
| `Energy Import counter (kWh)` | kWh | Cumulative energy import meter reading |
| `Reactive Energy Export (kvarh)` | kvarh | Reactive energy exported |
| `Reactive Energy Export counter (kvarh)` | kvarh | Cumulative reactive export meter |
| `Reactive Energy Import (kvarh)` | kvarh | Reactive energy imported |
| `Reactive Energy Import counter (kvarh)` | kvarh | Cumulative reactive import meter |
| `Energy Theoretical (kWh)` | kWh | Energy that would have been produced at full availability |
| `Energy Budget - Default (kWh)` | kWh | Budgeted energy for the interval |
| `Energy Budget (weather adjusted) (kWh)` | kWh | Weather-corrected energy budget |
| `Lost Production (Contractual) (kWh)` | kWh | Lost production under contractual availability definition |
| `Lost Production (Contractual Global) (kWh)` | kWh | Contractual global definition of lost production |
| `Lost Production (Contractual Custom) (kWh)` | kWh | Custom contractual lost production |
| `Lost Production (Time-based IEC B.2.2) (kWh)` | kWh | Lost production per IEC B.2.2 time-based method |
| `Lost Production (Time-based IEC B.2.3) (kWh)` | kWh | Lost production per IEC B.2.3 time-based method |
| `Lost Production (Time-based IEC B.2.4) (kWh)` | kWh | Lost production per IEC B.2.4 time-based method |
| `Lost Production (Time-based IEC B.3.2) (kWh)` | kWh | Lost production per IEC B.3.2 time-based method |
| `Lost Production (Production-based IEC B.2.2) (kWh)` | kWh | Lost production per IEC B.2.2 production-based method |
| `Lost Production (Production-based IEC B.2.3) (kWh)` | kWh | Lost production per IEC B.2.3 production-based method |
| `Lost Production (Production-based IEC B.3.2) (kWh)` | kWh | Lost production per IEC B.3.2 production-based method |
| `Lost Production to Downtime (kWh)` | kWh | Production lost due to turbine downtime |
| `Lost Production to Performance (kWh)` | kWh | Production lost due to underperformance |
| `Lost Production Total (kWh)` | kWh | Total lost production (all causes) |
| `Lost Production to Curtailment (Total) (kWh)` | kWh | Total curtailment losses |
| `Lost Production to Curtailment (Grid) (kWh)` | kWh | Curtailment due to grid constraints |
| `Lost Production to Curtailment (Noise) (kWh)` | kWh | Curtailment due to noise regulations |
| `Lost Production to Curtailment (Shadow) (kWh)` | kWh | Curtailment due to shadow flicker regulations |
| `Lost Production to Curtailment (Bats) (kWh)` | kWh | Curtailment for bat protection |
| `Lost Production to Curtailment (Birds) (kWh)` | kWh | Curtailment for bird protection |
| `Lost Production to Curtailment (Ice) (kWh)` | kWh | Curtailment due to icing conditions |
| `Lost Production to Curtailment (Sector Management) (kWh)` | kWh | Curtailment from sector management |
| `Lost Production to Curtailment (Technical) (kWh)` | kWh | Curtailment due to technical limits |
| `Lost Production to Curtailment (Marketing) (kWh)` | kWh | Curtailment due to energy market decisions |
| `Lost Production to Curtailment (Boat Action) (kWh)` | kWh | Curtailment due to marine vessel activity |
| `Lost Production to Curtailment (Grid Constraint) (kWh)` | kWh | Curtailment due to grid capacity constraints |
| `Lost Production to Downtime and Curtailment Total (kWh)` | kWh | Combined downtime and curtailment losses |
| `Compensated Lost Production (kWh)` | kWh | Lost production eligible for compensation |
| `Virtual Production (kWh)` | kWh | Hypothetical production used for availability calculations |
| `Rotor speed (RPM)` | RPM | Mean rotor rotational speed |
| `Rotor speed, Max (RPM)` | RPM | Maximum rotor speed |
| `Rotor speed, Min (RPM)` | RPM | Minimum rotor speed |
| `Rotor speed, Standard deviation (RPM)` | RPM | Std dev of rotor speed |
| `Generator RPM (RPM)` | RPM | Mean generator shaft speed |
| `Generator RPM, Max (RPM)` | RPM | Maximum generator speed |
| `Generator RPM, Min (RPM)` | RPM | Minimum generator speed |
| `Generator RPM, Standard deviation (RPM)` | RPM | Std dev of generator speed |
| `Gearbox speed (RPM)` | RPM | Mean gearbox output speed |
| `Gearbox speed, Max (RPM)` | RPM | Maximum gearbox speed |
| `Gearbox speed, Min (RPM)` | RPM | Minimum gearbox speed |
| `Gearbox speed, StdDev (RPM)` | RPM | Std dev of gearbox speed |
| `Blade angle (pitch position) A (°)` | degrees | Mean pitch angle of blade A |
| `Blade angle (pitch position) A, Max (°)` | degrees | Maximum pitch angle of blade A |
| `Blade angle (pitch position) A, Min (°)` | degrees | Minimum pitch angle of blade A |
| `Blade angle (pitch position) A, Standard deviation (°)` | degrees | Std dev of blade A pitch |
| `Blade angle (pitch position) B (°)` | degrees | Mean pitch angle of blade B |
| `Blade angle (pitch position) B, Max (°)` | degrees | Maximum pitch angle of blade B |
| `Blade angle (pitch position) B, Min (°)` | degrees | Minimum pitch angle of blade B |
| `Blade angle (pitch position) B, Standard deviation (°)` | degrees | Std dev of blade B pitch |
| `Blade angle (pitch position) C (°)` | degrees | Mean pitch angle of blade C |
| `Blade angle (pitch position) C, Max (°)` | degrees | Maximum pitch angle of blade C |
| `Blade angle (pitch position) C, Min (°)` | degrees | Minimum pitch angle of blade C |
| `Blade angle (pitch position) C, Standard deviation (°)` | degrees | Std dev of blade C pitch |
| `Yaw bearing angle (°)` | degrees | Absolute yaw bearing angle of the nacelle |
| `Yaw bearing angle, Max (°)` | degrees | Maximum yaw angle during interval |
| `Yaw bearing angle, Min (°)` | degrees | Minimum yaw angle during interval |
| `Yaw bearing angle, StdDev (°)` | degrees | Std dev of yaw angle |
| `Front bearing temperature (°C)` | °C | Main shaft front bearing temperature |
| `Front bearing temperature, Max (°C)` | °C | Maximum front bearing temperature |
| `Front bearing temperature, Min (°C)` | °C | Minimum front bearing temperature |
| `Front bearing temperature, Standard deviation (°C)` | °C | Std dev of front bearing temperature |
| `Rear bearing temperature (°C)` | °C | Main shaft rear bearing temperature |
| `Rear bearing temperature, Max (°C)` | °C | Maximum rear bearing temperature |
| `Rear bearing temperature, Min (°C)` | °C | Minimum rear bearing temperature |
| `Rear bearing temperature, Standard deviation (°C)` | °C | Std dev of rear bearing temperature |
| `Rotor bearing temp (°C)` | °C | Rotor bearing temperature |
| `Rotor bearing temp, Max (°C)` | °C | Maximum rotor bearing temperature |
| `Rotor bearing temp, Min (°C)` | °C | Minimum rotor bearing temperature |
| `Rotor bearing temp, StdDev (°C)` | °C | Std dev of rotor bearing temperature |
| `Generator bearing front temperature (°C)` | °C | Generator front bearing temperature |
| `Generator bearing front temperature, Max (°C)` | °C | Maximum generator front bearing temperature |
| `Generator bearing front temperature, Min (°C)` | °C | Minimum generator front bearing temperature |
| `Generator bearing front temperature, Std (°C)` | °C | Std dev of generator front bearing temperature |
| `Generator bearing rear temperature (°C)` | °C | Generator rear bearing temperature |
| `Generator bearing rear temperature, Max (°C)` | °C | Maximum generator rear bearing temperature |
| `Generator bearing rear temperature, Min (°C)` | °C | Minimum generator rear bearing temperature |
| `Generator bearing rear temperature, Std (°C)` | °C | Std dev of generator rear bearing temperature |
| `Stator temperature 1 (°C)` | °C | Generator stator winding temperature |
| `Stator temperature 1, Max (°C)` | °C | Maximum stator temperature |
| `Stator temperature 1, Min (°C)` | °C | Minimum stator temperature |
| `Stator temperature 1, StdDev (°C)` | °C | Std dev of stator temperature |
| `Gear oil temperature (°C)` | °C | Gearbox oil bulk temperature |
| `Gear oil temperature, Max (°C)` | °C | Maximum gear oil temperature |
| `Gear oil temperature, Min (°C)` | °C | Minimum gear oil temperature |
| `Gear oil temperature, Standard deviation (°C)` | °C | Std dev of gear oil temperature |
| `Gear oil inlet temperature (°C)` | °C | Oil temperature at the gearbox inlet |
| `Gear oil inlet temperature, Max (°C)` | °C | Maximum gear oil inlet temperature |
| `Gear oil inlet temperature, Min (°C)` | °C | Minimum gear oil inlet temperature |
| `Gear oil inlet temperature, StdDev (°C)` | °C | Std dev of gear oil inlet temperature |
| `Gear oil inlet pressure (bar)` | bar | Oil pressure at the gearbox inlet |
| `Gear oil inlet pressure, Max (bar)` | bar | Maximum inlet oil pressure |
| `Gear oil inlet pressure, Min (bar)` | bar | Minimum inlet oil pressure |
| `Gear oil inlet pressure, StdDev (bar)` | bar | Std dev of inlet oil pressure |
| `Gear oil pump pressure (bar)` | bar | Oil pressure at the gearbox pump |
| `Gear oil pump pressure, Max (bar)` | bar | Maximum pump pressure |
| `Gear oil pump pressure, Min (bar)` | bar | Minimum pump pressure |
| `Gear oil pump pressure, StdDev (bar)` | bar | Std dev of pump pressure |
| `Nacelle temperature (°C)` | °C | Air temperature inside the nacelle |
| `Nacelle temperature, Max (°C)` | °C | Maximum nacelle temperature |
| `Nacelle temperature, Min (°C)` | °C | Minimum nacelle temperature |
| `Nacelle temperature, Standard deviation (°C)` | °C | Std dev of nacelle temperature |
| `Nacelle ambient temperature (°C)` | °C | External ambient temperature measured at nacelle height |
| `Nacelle ambient temperature, Max (°C)` | °C | Maximum ambient temperature |
| `Nacelle ambient temperature, Min (°C)` | °C | Minimum ambient temperature |
| `Nacelle ambient temperature, StdDev (°C)` | °C | Std dev of ambient temperature |
| `Hub temperature (°C)` | °C | Temperature inside the rotor hub |
| `Hub temperature, min (°C)` | °C | Minimum hub temperature |
| `Hub temperature, max (°C)` | °C | Maximum hub temperature |
| `Hub temperature, standard deviation (°C)` | °C | Std dev of hub temperature |
| `Transformer temperature (°C)` | °C | Turbine transformer temperature |
| `Transformer temperature, Max (°C)` | °C | Maximum transformer temperature |
| `Transformer temperature, Min (°C)` | °C | Minimum transformer temperature |
| `Transformer temperature, StdDev (°C)` | °C | Std dev of transformer temperature |
| `Transformer cell temperature (°C)` | °C | Temperature in the transformer enclosure |
| `Transformer cell temperature, Max (°C)` | °C | Maximum transformer cell temperature |
| `Transformer cell temperature, Min (°C)` | °C | Minimum transformer cell temperature |
| `Transformer cell temperature, StdDev (°C)` | °C | Std dev of transformer cell temperature |
| `Temp. top box (°C)` | °C | Temperature in the top-box (nacelle electronics) |
| `Temp. top box, Max (°C)` | °C | Maximum top-box temperature |
| `Temp. top box, Min (°C)` | °C | Minimum top-box temperature |
| `Temp. top box, StdDev (°C)` | °C | Std dev of top-box temperature |
| `Ambient temperature (converter) (°C)` | °C | Ambient temperature at the power converter |
| `Ambient temperature (converter), Max (°C)` | °C | Maximum converter ambient temperature |
| `Ambient temperature (converter), Min (°C)` | °C | Minimum converter ambient temperature |
| `Ambient temperature (converter), StdDev (°C)` | °C | Std dev of converter ambient temperature |
| `Temperature motor axis 1 (°C)` | °C | Motor/actuator temperature on pitch axis 1 |
| `Temperature motor axis 1, Max (°C)` | °C | Maximum axis 1 motor temperature |
| `Temperature motor axis 1, Min (°C)` | °C | Minimum axis 1 motor temperature |
| `Temperature motor axis 1, StdDev (°C)` | °C | Std dev of axis 1 motor temperature |
| `Temperature motor axis 2 (°C)` | °C | Motor/actuator temperature on pitch axis 2 |
| `Temperature motor axis 2, Max (°C)` | °C | Maximum axis 2 motor temperature |
| `Temperature motor axis 2, Min (°C)` | °C | Minimum axis 2 motor temperature |
| `Temperature motor axis 2, StdDev (°C)` | °C | Std dev of axis 2 motor temperature |
| `Temperature motor axis 3 (°C)` | °C | Motor/actuator temperature on pitch axis 3 |
| `Temperature motor axis 3, Max (°C)` | °C | Maximum axis 3 motor temperature |
| `Temperature motor axis 3, Min (°C)` | °C | Minimum axis 3 motor temperature |
| `Temperature motor axis 3, StdDev (°C)` | °C | Std dev of axis 3 motor temperature |
| `CPU temperature (°C)` | °C | Control system CPU temperature |
| `CPU temperature, Max (°C)` | °C | Maximum CPU temperature |
| `CPU temperature, Min (°C)` | °C | Minimum CPU temperature |
| `CPU temperature, StdDev (°C)` | °C | Std dev of CPU temperature |
| `Voltage L1 / U (V)` | V | Mean phase L1 voltage |
| `Voltage L1 / U, Max (V)` | V | Maximum L1 voltage |
| `Voltage L1 / U, Min (V)` | V | Minimum L1 voltage |
| `Voltage L1 / U, Standard deviation (V)` | V | Std dev of L1 voltage |
| `Voltage L2 / V (V)` | V | Mean phase L2 voltage |
| `Voltage L2 / V, Max (V)` | V | Maximum L2 voltage |
| `Voltage L2 / V, Min (V)` | V | Minimum L2 voltage |
| `Voltage L2 / V, Standard deviation (V)` | V | Std dev of L2 voltage |
| `Voltage L3 / W (V)` | V | Mean phase L3 voltage |
| `Voltage L3 / W, Max (V)` | V | Maximum L3 voltage |
| `Voltage L3 / W, Min (V)` | V | Minimum L3 voltage |
| `Voltage L3 / W, Standard deviation (V)` | V | Std dev of L3 voltage |
| `Grid voltage (V)` | V | Mean grid-side voltage |
| `Grid voltage, Max (V)` | V | Maximum grid voltage |
| `Grid voltage, Min (V)` | V | Minimum grid voltage |
| `Grid voltage, Standard deviation (V)` | V | Std dev of grid voltage |
| `Current L1 / U (A)` | A | Mean phase L1 current |
| `Current L1 / U, max (A)` | A | Maximum L1 current |
| `Current L1 / U, min (A)` | A | Minimum L1 current |
| `Current L1 / U, StdDev (A)` | A | Std dev of L1 current |
| `Current L2 / V (A)` | A | Mean phase L2 current |
| `Current L2 / V, max (A)` | A | Maximum L2 current |
| `Current L2 / V, min (A)` | A | Minimum L2 current |
| `Current L2 / V, StdDev (A)` | A | Std dev of L2 current |
| `Current L3 / W (A)` | A | Mean phase L3 current |
| `Current L3 / W, max (A)` | A | Maximum L3 current |
| `Current L3 / W, min (A)` | A | Minimum L3 current |
| `Current L3 / W, StdDev (A)` | A | Std dev of L3 current |
| `Grid current (A)` | A | Mean grid-side current |
| `Grid current, Max (A)` | A | Maximum grid current |
| `Grid current, Min (A)` | A | Minimum grid current |
| `Grid current, StdDev (A)` | A | Std dev of grid current |
| `Motor current axis 1 (A)` | A | Current drawn by pitch motor axis 1 |
| `Motor current axis 1, Max (A)` | A | Maximum axis 1 motor current |
| `Motor current axis 1, Min (A)` | A | Minimum axis 1 motor current |
| `Motor current axis 1, StdDev (A)` | A | Std dev of axis 1 motor current |
| `Motor current axis 2 (A)` | A | Current drawn by pitch motor axis 2 |
| `Motor current axis 2, Max (A)` | A | Maximum axis 2 motor current |
| `Motor current axis 2, Min (A)` | A | Minimum axis 2 motor current |
| `Motor current axis 2, StdDev (A)` | A | Std dev of axis 2 motor current |
| `Motor current axis 3 (A)` | A | Current drawn by pitch motor axis 3 |
| `Motor current axis 3, Max (A)` | A | Maximum axis 3 motor current |
| `Motor current axis 3, Min (A)` | A | Minimum axis 3 motor current |
| `Motor current axis 3, StdDev (A)` | A | Std dev of axis 3 motor current |
| `Grid frequency (Hz)` | Hz | Mean grid frequency |
| `Grid frequency, Max (Hz)` | Hz | Maximum grid frequency |
| `Grid frequency, Min (Hz)` | Hz | Minimum grid frequency |
| `Grid frequency, Standard deviation (Hz)` | Hz | Std dev of grid frequency |
| `Drive train acceleration (mm/s²)` | mm/s² | Vibration acceleration measured on the drive train |
| `Drive train acceleration, Max (mm/s²)` | mm/s² | Maximum drive train vibration |
| `Drive train acceleration, Min (mm/s²)` | mm/s² | Minimum drive train vibration |
| `Drive train acceleration, StdDev (mm/s²)` | mm/s² | Std dev of drive train vibration |
| `Tower Acceleration X (mm/s²)` | mm/s² | Tower fore-aft vibration acceleration |
| `Tower Acceleration X, Max (mm/s²)` | mm/s² | Maximum fore-aft tower vibration |
| `Tower Acceleration X, Min (mm/s²)` | mm/s² | Minimum fore-aft tower vibration |
| `Tower Acceleration X, StdDev (mm/s²)` | mm/s² | Std dev of fore-aft tower vibration |
| `Tower Acceleration Y (mm/s²)` | mm/s² | Tower side-to-side vibration acceleration |
| `Tower Acceleration Y, Max (mm/s²)` | mm/s² | Maximum side-to-side vibration |
| `Tower Acceleration Y, Min (mm/s²)` | mm/s² | Minimum side-to-side vibration |
| `Tower Acceleration Y, StdDev (mm/s²)` | mm/s² | Std dev of side-to-side vibration |
| `Capacity factor` | — | Ratio of actual energy output to rated capacity |
| `Data Availability` | — | Fraction of the interval with valid data |
| `Time-based Contractual Avail.` | — | Contractual time-based availability metric |
| `Time-based IEC B.2.2 (Users View)` | — | IEC B.2.2 time-based availability (user perspective) |
| `Time-based IEC B.2.3 (Users View)` | — | IEC B.2.3 time-based availability |
| `Time-based IEC B.2.4 (Users View)` | — | IEC B.2.4 time-based availability |
| `Time-based IEC B.3.2 (Manufacturers View)` | — | IEC B.3.2 time-based availability (OEM perspective) |
| `Production-based IEC B.2.2 (Users View)` | — | IEC B.2.2 production-based availability |
| `Production-based IEC B.2.3 (Users View)` | — | IEC B.2.3 production-based availability |
| `Production-based IEC B.3.2 (Manufacturers View)` | — | IEC B.3.2 production-based availability (OEM) |
| `Time-based System Avail.` | — | Overall system time-based availability |
| `Production-based System Avail.` | — | Overall system production-based availability |
| `Time-based Contractual Avail. (Global)` | — | Global contractual time-based availability |
| `Time-based Contractual Avail. (Custom)` | — | Custom contractual time-based availability |
| `Production-based Contractual Avail.` | — | Contractual production-based availability |
| `Production-based Contractual Avail. (Global)` | — | Global contractual production-based availability |
| `Production-based Contractual Avail. (Custom)` | — | Custom contractual production-based availability |
| `Equivalent Full Load Hours (s)` | s | Seconds of operation at full rated power equivalent |
| `Equivalent Full Load Hours counter (s)` | s | Cumulative full-load-hour counter |
| `Sunset Delta (s)` | s | Seconds since/until sunset (used for curtailment triggers) |
| `Sunrise Delta (s)` | s | Seconds since/until sunrise |
| `Cable windings from calibration point` | — | Number of cable twist windings from zero-twist reference |
| `Metal particle count` | — | Count of metallic particles detected in oil (wear indicator) |
| `Metal particle count counter` | — | Cumulative metal particle counter |
| `Night Time` | — | Flag indicating whether the interval falls in night hours |
| `Production Factor` | — | Ratio of actual to theoretical production |
| `Performance Index` | — | Turbine performance index relative to reference |
| `Investment Performance Ratio` | — | Financial performance ratio |
| `Operating Performance Ratio` | — | Operational performance ratio |
| `MTBF (Contractual Global) (h)` | h | Mean time between failures (contractual global) |
| `MTTR (Contractual Global) (h)` | h | Mean time to repair (contractual global) |

#### Status columns — field reference

| Column | Description |
|--------|-------------|
| `Timestamp start` | Date and time when this status event began |
| `Timestamp end` | Date and time when this status event ended |
| `Duration` | Duration of the event as `HH:MM:SS` string |
| `Status` | Human-readable status label (e.g. "Full Performance", "Downtime") |
| `Code` | Numeric status code (0 = normal initial record) |
| `Message` | Detailed status message from the SCADA system |
| `Comment` | Optional operator comment added manually |
| `Service contract category` | Classification of the event under the service contract |
| `IEC category` | IEC 61400-26 availability category (e.g. T1, T3, T4…) |
| `Global contract category` | Event category under the global contract definition |
| `Turbine` | Turbine identifier number |

#### Full hourly record example

```json
{
  "farm": "kelmarsh",
  "turbine": "turbine_2",
  "hour_start": "2018-05-30 20:00:00",
  "hour_end": "2018-05-30 20:59:59",
  "data_missing": false,
  "data_points": [
    {
      "Date and time": "2018-05-30 20:00:00",
      "Wind speed (m/s)": 7.1,
      "Wind speed, Standard deviation (m/s)": 0.4,
      "Wind speed, Minimum (m/s)": 6.5,
      "Wind speed, Maximum (m/s)": 7.8,
      "Density adjusted wind speed (m/s)": 7.0,
      "Wind direction (°)": 214.3,
      "Nacelle position (°)": 212.1,
      "Vane position 1+2 (°)": 2.2,
      "Power (kW)": 1204.5,
      "Power, Standard deviation (kW)": 38.2,
      "Power, Minimum (kW)": 1120.0,
      "Power, Maximum (kW)": 1290.0,
      "Rotor speed (RPM)": 14.7,
      "Generator RPM (RPM)": 1470.0,
      "Blade angle (pitch position) A (°)": 1.2,
      "Blade angle (pitch position) B (°)": 1.1,
      "Blade angle (pitch position) C (°)": 1.3,
      "Nacelle temperature (°C)": 32.4,
      "Nacelle ambient temperature (°C)": 11.2,
      "Gear oil temperature (°C)": 45.1,
      "Gear oil inlet temperature (°C)": 43.8,
      "Generator bearing front temperature (°C)": 58.3,
      "Generator bearing rear temperature (°C)": 60.1,
      "Front bearing temperature (°C)": 38.5,
      "Rear bearing temperature (°C)": 37.9,
      "Stator temperature 1 (°C)": 72.6,
      "Grid voltage (V)": 690.2,
      "Grid current (A)": 1012.4,
      "Grid frequency (Hz)": 50.01,
      "Reactive power (kvar)": 42.0,
      "Power factor (cosphi)": 0.999,
      "Energy Export (kWh)": 200.75,
      "Drive train acceleration (mm/s²)": 0.82,
      "Tower Acceleration X (mm/s²)": 0.31,
      "Tower Acceleration Y (mm/s²)": 0.28,
      "Capacity factor": 0.48,
      "Data Availability": 1.0
    }
  ],
  "statuses": [
    {
      "Timestamp start": "2018-05-30 20:15:00",
      "Timestamp end": "2018-05-30 20:23:00",
      "Duration": "00:08:00",
      "Status": "Downtime",
      "Code": 105,
      "Message": "Grid disturbance - automatic restart",
      "Comment": null,
      "Service contract category": "Force Majeure",
      "IEC category": "T4",
      "Global contract category": "External",
      "Turbine": 2
    }
  ]
}
```

### Step 5 — Compute Statistical Summary

For every **numeric column** found in `data_points`:

- **Mean** across the 5 data points
- **Standard deviation** (population or sample, consistently applied)

The summary record mirrors the hourly record but replaces `data_points` with `stats`:

```json
{
  "farm":       "kelmarsh",
  "turbine":    "turbine_2",
  "hour_start": "2018-05-30 20:00:00",
  "hour_end":   "2018-05-30 20:59:59",
  "data_missing": false,
  "stats": {
    "Wind speed (m/s)":   { "mean": 7.24, "std": 0.31 },
    "Power (kW)":         { "mean": 1215.6, "std": 42.1 },
    "Rotor speed (rpm)":  { "mean": 14.8,  "std": 0.6 }
  },
  "status_count": 1,
  "statuses": [ "..." ]
}
```

This structure allows **like-hour comparisons** (e.g. all Monday 8 PM hours across different weeks/years) without re-fetching raw data.

---

## Output Files

### `output/{farm}_{turbine}_raw.json`

A JSON array where each element is one **hourly record** as described in Step 4.

```json
[
  { "farm": "kelmarsh", "turbine": "turbine_2", "hour_start": "...", "data_points": [], "statuses": [] },
  "..."
]
```

### `output/{farm}_{turbine}_summary.json`

A JSON array where each element is one **hourly summary** as described in Step 5.

```json
[
  { "farm": "kelmarsh", "turbine": "turbine_2", "hour_start": "...", "stats": {}, "statuses": [] },
  "..."
]
```

---

## Key Implementation Details

| Concern | Approach |
|---------|----------|
| **HTTP client** | `httpx` (already used in tests); synchronous is fine, async optional for speed |
| **Weather API** | OpenWeatherMap One Call 3.0 Time Machine; key via `OWM_API_KEY` env var |
| **Weather caching** | In-memory cache per run; optional `weather_cache.json` on disk (`--cache-weather`) |
| **Farm coordinates** | Stored in `farms.json`; passed as `lat`/`lon` to OWM |
| **Statistics** | `statistics.mean()` / `statistics.stdev()` from stdlib, or `numpy`/`pandas` for brevity |
| **Date iteration** | `datetime` + `timedelta(hours=1)` loop |
| **Numeric column detection** | Check `isinstance(value, (int, float))` on the first non-null row |
| **Error handling** | Catch HTTP errors and timeouts per request; log and continue; mark hours with `fetch_error: true` |
| **Retry logic** | Simple 3-attempt retry with 2-second backoff for transient failures |
| **CLI interface** | `argparse` with `--farm`, `--turbine`, `--start`, `--end`, `--output-dir`, `--columns` flags |
| **Progress reporting** | `tqdm` progress bar over the list of hourly windows |
| **Logging** | Python `logging` module writing to both console and a `run.log` file |

---

## Example CLI Usage

```bash
# Collect one full day for Kelmarsh turbine 2
python collect_hourly.py --farm kelmarsh --turbine turbine_2 \
    --start "2018-05-30 00:00:00" --end "2018-05-30 23:59:59"

# Same but cache OWM responses to disk to avoid re-fetching on re-runs
python collect_hourly.py --farm kelmarsh --turbine turbine_2 \
    --start "2018-05-30 00:00:00" --end "2018-05-30 23:59:59" \
    --cache-weather

# Skip OWM entirely (no API key needed, weather field will be null)
python collect_hourly.py --farm kelmarsh --turbine turbine_2 \
    --start "2018-05-30 00:00:00" --end "2018-05-30 23:59:59" \
    --no-weather

# Collect across all known farms and turbines using defaults
python collect_hourly.py --all
```

---

## How an LLM Can Use the Output

- **Anomaly detection**: Compare `stats.mean` for `Power (kW)` at the same hour-of-day across weeks; flag outliers.
- **Status correlation**: Hours with `status_count > 0` can be examined to see whether sensor readings diverged from normal before/during the event.
- **Performance benchmarking**: Group summaries by `hour_start` hour-of-day and wind speed bin to build a reference power curve.
- **Natural language reporting**: Feed a single hourly summary record to an LLM and ask *"Was turbine performance normal during this hour?"*

---

## File Structure After a Run

```
output/
├── kelmarsh_turbine_1_raw.json
├── kelmarsh_turbine_1_summary.json
├── kelmarsh_turbine_2_raw.json
├── kelmarsh_turbine_2_summary.json
├── penmanshiel_turbine_1_raw.json
├── penmanshiel_turbine_1_summary.json
└── ...
run.log
```

