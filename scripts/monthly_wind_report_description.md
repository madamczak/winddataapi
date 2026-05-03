# Monthly Wind Speed Visualisation – Approach Description

## Overview

This document describes the approach for visualising wind turbine summary data collected
from the **kelmarsh** (and other) wind farms. The goal is to build a human-readable,
interactive HTML report that lets an analyst — or an LLM — quickly compare wind speed
(and other parameters) hour-by-hour across multiple years for the first day of each month.

---

## Data Source

- **Location:** `crawler/output/{farm}/{turbine}/`
- **File pattern:** `YYYY-MM-DD_HH_summary.json`
- **Key fields used per file:**
  - `hour_start` — ISO datetime string, e.g. `"2018-01-01 02:00:00"`
  - `data_missing` / `fetch_error` — boolean flags; files with these set are skipped
  - `stats` — dict of parameter → `{ "mean": float, "std": float, "n": int }`
    - Primary field: `Wind speed (m/s)`
    - Future fields: `Power (kW)`, `Rotor speed (RPM)`, `Nacelle ambient temperature (°C)`, etc.
  - `status_count`, `statuses` — fault/status events during that hour

Only files whose date is the **1st of the month** are loaded; all other days are ignored
for this report (to compare the same calendar day across years).

---

## Report Structure

```
HTML page
├── Header  (farm name, turbine, description)
├── Info bar  (years available, months with data)
├── Tab navigation  [January] [February] … [December]
└── Tab panels (one per month)
    ├── Heading (month name, farm, turbine)
    └── Table
         ├── Column headers: Year (2016, 2017, 2018, …)
         ├── Row label: Hour (00:00, 01:00, … 23:00)
         └── Cell value: mean wind speed (m/s)
                         colour-coded by magnitude
```

### Table Layout

| Hour  | 2016  | 2017  | 2018  | … |
|-------|-------|-------|-------|---|
| 00:00 | 7.23  | 5.11  | 10.86 | … |
| 01:00 | –     | 6.40  | 9.91  | … |
| …     | …     | …     | …     | … |
| 23:00 | 4.55  | –     | 8.33  | … |

- `–` means no data file exists or the file is marked as missing/error.
- Cells have a **colour gradient**: low wind → blue, medium → purple, high → red.
  This makes it easy to spot patterns (e.g. consistently high-wind years at a glance).

---

## Implementation

### Script

`scripts/monthly_wind_report.py`

**Steps:**
1. Glob all `*_summary.json` files under `crawler/output/{farm}/{turbine}/`.
2. Parse `hour_start` from each file; keep only records where `day == 1`.
3. Skip files where `data_missing` or `fetch_error` is `True`, or where the
   `Wind speed (m/s)` stats key is absent.
4. Store valid records in a dict keyed by `(month, year, hour)`.
5. Determine the set of months and years present in the data.
6. Generate a self-contained HTML file with one tab per month.
7. Inside each tab, render an HTML `<table>` with years as columns and hours as rows.
8. Cell background colour is derived from a linear interpolation:
   `intensity = min(wind_speed / 20.0, 1.0)` → mapped to an RGB triplet.

**Run:**
```bash
python scripts/monthly_wind_report.py --farm kelmarsh --turbine turbine_2
# Output: monthly_wind_report.html (in project root)

# Custom output path:
python scripts/monthly_wind_report.py --farm kelmarsh --turbine turbine_2 \
    --output /path/to/report.html
```

---

## Extending to More Parameters

The script defines a `DISPLAY_FIELDS` dictionary at the top:

```python
DISPLAY_FIELDS = {
    'wind':  ('Wind Speed (m/s)',    'Wind speed (m/s)'),
    'power': ('Power (kW)',          'Power (kW)'),
    'rotor': ('Rotor Speed (RPM)',   'Rotor speed (RPM)'),
    'temp':  ('Nacelle Temp (°C)',   'Nacelle ambient temperature (°C)'),
}
```

To add a **parameter switcher** (e.g. buttons to toggle between wind speed / power /
temperature within the same tab), the next iteration should:

1. Accept a `--field wind|power|rotor|temp` CLI argument (or render all in separate
   sub-tables within the same tab).
2. Use the `cell_value(stats, field_key)` helper already present to pull any stat field.
3. Adjust the colour scale per parameter (wind: 0–20 m/s, power: 0–2500 kW, etc.).

---

## LLM Usage Notes

This document and the generated HTML can serve as context for an LLM tasked with:

- **Trend detection:** "For which months does wind speed decrease year-over-year?"
- **Anomaly detection:** "Are there hours on Jan 1st where one year is a clear outlier?"
- **Correlation analysis:** "Do years with high wind speed on Jan 1st also show high power?"
- **Gap identification:** "Which year/month combinations are missing the most data?"

Provide the LLM with:
1. This `.md` description file.
2. The raw summary JSON files for the hours of interest, **or**
3. A CSV dump of the `(month, year, hour, wind_mean, power_mean, …)` table.

---

## File Outputs

| File | Description |
|------|-------------|
| `monthly_wind_report.html` | Self-contained HTML report (no external dependencies) |
| `scripts/monthly_wind_report.py` | Script that generates the report |
| `crawler/output/{farm}/{turbine}/YYYY-MM-01_HH_summary.json` | Source data files |

---

## Assumptions & Limitations

- Only the **1st day of each month** is used per tab. This is a fixed reference point
  to allow year-over-year comparison on identical calendar dates.
- Data availability varies by year; many cells may be `–` for early or late years.
- Weather data (`weather` field in summary JSON) is not yet integrated into this report.
- The colour scale is currently fixed; a per-column normalisation would be more accurate
  for parameters with very different ranges.

