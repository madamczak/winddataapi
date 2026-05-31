"""
scan.py — Phase 2: Crawl a date range, compute ΔT residuals against the baseline.

For each hour of each turbine in the given date range:
  1. Fetch the hour's SCADA data from the API.
  2. Assign the hour to its operating condition bin (wind × power × ambient).
  3. Compute ΔT = T_measured − T_baseline[bin][col] for every temperature column.
  4. Stream the residual record as a JSONL line to the per-turbine residuals file.

Records for masked maintenance windows are silently skipped; records where the
operating condition bin has no baseline entry (too sparse in Phase 1) are also
skipped — the bin is logged as a data gap.

Output schema (one JSONL line per turbine per hour):
{
  "farm":         "kelmarsh",
  "turbine":      "turbine_2",
  "date":         "2020-03-15",
  "hour":         14,
  "op_bin":       "(8-10, 1500-2000, 10-20)",
  "deltas":       {"Generator bearing front temperature (°C)": 2.3, ...},
  "wind_mean":    10.2,
  "power_mean":   1734.0,
  "ambient_mean": 13.4,
  "timestamp_utc":"2026-05-20T10:00:00+00:00"
}
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests

from .baseline import _col_values, _fetch_hour, _is_masked, _safe_mean
from .bins import get_bin
from .config import (
    COND_COLS,
    RESIDUALS_DIR,
    TEMP_COLS,
)
from .machine_logger import log


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def scan_period(
    farm: str,
    turbine: str,
    start_date: date,
    end_date: date,
    baseline: dict[str, dict[str, float]],
    mask_windows: list[tuple[date, date]],
    residuals_dir: Path = RESIDUALS_DIR,
) -> dict:
    """
    Phase 2 — Compute ΔT residuals for every hour in the scan period.

    Parameters
    ----------
    farm, turbine : str
        Target turbine.
    start_date, end_date : date
        Inclusive scan range (should start after the baseline end date).
    baseline : dict
        Pre-loaded baseline from baseline.load_baseline().  Must be non-empty.
    mask_windows : list of (date, date)
        Maintenance windows to skip (from service_mask.fetch_mask_windows).
    residuals_dir : Path
        Directory where per-turbine JSONL files are written.

    Returns
    -------
    Summary dict: {hours_scanned, hours_skipped, hours_no_bin, residuals_written}
    """
    if not baseline:
        log("WARN", "scan_no_baseline", farm=farm, turbine=turbine,
            note="Baseline is empty — run Phase 1 (baseline.build_baseline) first.")
        return {"error": "no_baseline"}

    residuals_dir.mkdir(parents=True, exist_ok=True)
    out_path = residuals_dir / f"{farm}_{turbine}.jsonl"

    log("INFO", "scan_start", farm=farm, turbine=turbine,
        start=str(start_date), end=str(end_date),
        baseline_bins=len(baseline))

    session = requests.Session()
    all_cols = TEMP_COLS + COND_COLS

    hours_scanned  = 0
    hours_skipped  = 0
    hours_no_bin   = 0
    residuals_written = 0

    with open(out_path, "a", encoding="utf-8") as fh:
        d = start_date
        while d <= end_date:
            if _is_masked(d, mask_windows):
                hours_skipped += 24
                d += timedelta(days=1)
                continue

            for hour in range(24):
                data = _fetch_hour(session, farm, turbine, d.isoformat(), hour, all_cols)
                if data is None:
                    hours_skipped += 1
                    continue

                wind    = _safe_mean(_col_values(data, "Wind speed (m/s)"))
                power   = _safe_mean(_col_values(data, "Power (kW)"))
                ambient = _safe_mean(_col_values(data, "Nacelle ambient temperature (°C)"))

                if any(v is None for v in [wind, power, ambient]):
                    hours_skipped += 1
                    continue

                bin_key = get_bin(wind, power, ambient)  # type: ignore[arg-type]
                bin_baseline = baseline.get(bin_key)

                if bin_baseline is None:
                    # No baseline for this operating condition — cannot compute ΔT
                    hours_no_bin += 1
                    log("DEBUG", "scan_no_bin_entry",
                        farm=farm, turbine=turbine, date=d.isoformat(), hour=hour, bin=bin_key)
                    continue

                # Compute ΔT for every temperature column that has a baseline entry
                deltas: dict[str, Optional[float]] = {}
                for col in TEMP_COLS:
                    t_baseline = bin_baseline.get(col)
                    if t_baseline is None:
                        continue
                    col_vals = _col_values(data, col)
                    t_measured = _safe_mean(col_vals)
                    if t_measured is not None:
                        deltas[col] = round(t_measured - t_baseline, 3)

                if not deltas:
                    hours_skipped += 1
                    continue

                record = {
                    "farm":          farm,
                    "turbine":       turbine,
                    "date":          d.isoformat(),
                    "hour":          hour,
                    "op_bin":        bin_key,
                    "deltas":        deltas,
                    "wind_mean":     round(wind, 2),    # type: ignore[arg-type]
                    "power_mean":    round(power, 1),   # type: ignore[arg-type]
                    "ambient_mean":  round(ambient, 2), # type: ignore[arg-type]
                    "timestamp_utc": _now_utc(),
                }
                fh.write(json.dumps(record) + "\n")
                residuals_written += 1
                hours_scanned += 1

            d += timedelta(days=1)

    summary = {
        "hours_scanned":    hours_scanned,
        "hours_skipped":    hours_skipped,
        "hours_no_bin":     hours_no_bin,
        "residuals_written": residuals_written,
    }
    log("INFO", "scan_done", farm=farm, turbine=turbine, **summary)
    return summary


# ---------------------------------------------------------------------------
# Reader: load residuals back for drift detection
# ---------------------------------------------------------------------------

def load_residuals(
    farm: str,
    turbine: str,
    residuals_dir: Path = RESIDUALS_DIR,
) -> list[dict]:
    """
    Load all residual records for a turbine from its JSONL file.

    Returns a list of dicts sorted by (date, hour), ready to pass to
    drift_detect.detect_drift().
    """
    path = residuals_dir / f"{farm}_{turbine}.jsonl"
    if not path.exists():
        return []

    records = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

    # Flatten: one dict per (date, hour, col, delta_t) — needed by detect_drift
    flat: list[dict] = []
    for rec in records:
        for col, delta in rec.get("deltas", {}).items():
            flat.append({
                "date":     rec["date"],
                "hour":     rec["hour"],
                "col":      col,
                "delta_t":  delta,
                "op_bin":   rec.get("op_bin"),
            })

    flat.sort(key=lambda r: (r["date"], r["hour"]))
    return flat


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

