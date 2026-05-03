"""
collector.py — core data collection pipeline.

Queries the wind farm API hour by hour, attaches weather and status,
computes per-hour statistics, and hands results to a StorageAdapter.
"""

from __future__ import annotations

import json
import logging
import os
import statistics
import time
from datetime import datetime, timedelta
from typing import Any

import httpx
from tqdm import tqdm

from storage import StorageAdapter
from weather import WeatherClient

logger = logging.getLogger(__name__)

API_BASE = os.environ.get("API_BASE", "http://localhost:8000")
MAX_RETRIES = 3
RETRY_BACKOFF = 5  # seconds


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_collection(
    farms_cfg: dict,
    start_dt: datetime,
    end_dt: datetime,
    column_cfg: dict,
    storage: StorageAdapter,
    weather_client: WeatherClient | None,
    farms_filter: list[str] | None = None,
    turbines_filter: list[str] | None = None,
) -> dict:
    """
    Main collection loop.

    Returns a stats dict used for the final run summary.
    """
    stats = {
        "hours_total": 0,
        "hours_ok": 0,
        "hours_skipped": 0,
        "hours_missing": 0,
        "fetch_errors": 0,
        "files_written": 0,
    }

    hour_windows = list(_iter_hours(start_dt, end_dt))

    for farm_name, farm_info in farms_cfg.items():
        if farms_filter and farm_name not in farms_filter:
            continue

        turbines = farm_info["turbines"]
        if turbines_filter:
            turbines = [t for t in turbines if t in turbines_filter]

        lat = farm_info["lat"]
        lon = farm_info["lon"]

        desc = f"{farm_name} [{len(turbines)} turbines, {len(hour_windows)} hours]"
        for hour_start, hour_end in tqdm(hour_windows, desc=desc, unit="hr"):
            stats["hours_total"] += len(turbines)

            # --- fetch weather once per farm per hour ---
            weather_snapshot = None
            if weather_client is not None:
                weather_snapshot = weather_client.fetch(
                    farm_name, lat, lon, _fmt(hour_start)
                )

            hour_slug = hour_start.strftime("%Y-%m-%d_%H")

            for turbine in turbines:
                raw_key = f"{farm_name}/{turbine}/{hour_slug}_raw.json"
                summary_key = f"{farm_name}/{turbine}/{hour_slug}_summary.json"

                # --- skip already collected hours ---
                if storage.exists(raw_key) and storage.exists(summary_key):
                    logger.info("Skipping (already exists): %s", raw_key)
                    stats["hours_skipped"] += 1
                    continue
                record, summary = _process_hour(
                    farm=farm_name,
                    turbine=turbine,
                    hour_start=hour_start,
                    hour_end=hour_end,
                    column_cfg=column_cfg,
                    weather_snapshot=weather_snapshot,
                )

                if record.get("fetch_error"):
                    stats["fetch_errors"] += 1
                elif record.get("data_missing"):
                    stats["hours_missing"] += 1
                else:
                    stats["hours_ok"] += 1

                # --- one file per turbine per hour ---
                storage.write(raw_key, json.dumps(record, indent=2))
                storage.write(summary_key, json.dumps(summary, indent=2))
                stats["files_written"] += 2
                logger.info("Written: %s + %s", raw_key, summary_key)

    return stats


# ---------------------------------------------------------------------------
# Per-hour processing
# ---------------------------------------------------------------------------

def _process_hour(
    farm: str,
    turbine: str,
    hour_start: datetime,
    hour_end: datetime,
    column_cfg: dict,
    weather_snapshot: dict | None,
) -> tuple[dict, dict]:
    start_str = _fmt(hour_start)
    end_str = _fmt(hour_end)

    # 1. Fetch data
    data_rows, data_error = _query_api(farm, "data", turbine, start_str, end_str)
    # 2. Fetch status
    status_rows, _ = _query_api(farm, "status", turbine, start_str, end_str)

    # Apply column filtering
    data_rows = _filter_columns(data_rows, column_cfg.get("data"), always_keep="Date and time")
    status_rows = _filter_columns(status_rows, column_cfg.get("status"))

    data_missing = len(data_rows) == 0

    record: dict[str, Any] = {
        "farm": farm,
        "turbine": turbine,
        "hour_start": start_str,
        "hour_end": end_str,
        "data_missing": data_missing,
        "fetch_error": data_error,
        "weather": weather_snapshot,
        "data_points": data_rows,
        "statuses": status_rows,
    }

    summary: dict[str, Any] = {
        "farm": farm,
        "turbine": turbine,
        "hour_start": start_str,
        "hour_end": end_str,
        "data_missing": data_missing,
        "fetch_error": data_error,
        "weather": weather_snapshot,
        "stats": _compute_stats(data_rows),
        "status_count": len(status_rows),
        "statuses": status_rows,
    }

    return record, summary


# ---------------------------------------------------------------------------
# API query with retry
# ---------------------------------------------------------------------------

def _query_api(
    farm: str, data_type: str, turbine: str, start: str, end: str
) -> tuple[list[dict], bool]:
    url = f"{API_BASE}/farms/{farm}/{data_type}/turbines/{turbine}/query"
    params = {"start": start, "end": end}

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = httpx.get(url, params=params, timeout=360, verify=False)
            resp.raise_for_status()
            rows = resp.json().get("rows", [])
            return rows, False
        except Exception as exc:
            logger.warning(
                "Attempt %d/%d failed for %s/%s/%s [%s-%s]: %s",
                attempt, MAX_RETRIES, farm, data_type, turbine, start, end, exc,
            )
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF)

    logger.error("All retries exhausted for %s/%s/%s [%s]", farm, data_type, turbine, start)
    return [], True


# ---------------------------------------------------------------------------
# Stats computation
# ---------------------------------------------------------------------------

def _compute_stats(rows: list[dict]) -> dict:
    if not rows:
        return {}

    # Collect numeric columns from all rows
    numeric_cols: dict[str, list[float]] = {}
    for row in rows:
        for col, val in row.items():
            if col == "Date and time":
                continue
            if isinstance(val, (int, float)) and val is not None:
                numeric_cols.setdefault(col, []).append(float(val))
            elif isinstance(val, str):
                try:
                    numeric_cols.setdefault(col, []).append(float(val))
                except (ValueError, TypeError):
                    pass

    result = {}
    for col, values in numeric_cols.items():
        if not values:
            continue
        mean_val = statistics.mean(values)
        std_val = statistics.stdev(values) if len(values) > 1 else 0.0
        result[col] = {
            "mean": round(mean_val, 4),
            "std": round(std_val, 4),
            "n": len(values),
        }
    return result


# ---------------------------------------------------------------------------
# Column filtering
# ---------------------------------------------------------------------------

def _filter_columns(
    rows: list[dict],
    keep_cols: list[str] | None,
    always_keep: str | None = None,
) -> list[dict]:
    if keep_cols is None:
        return rows  # no filter configured → keep everything

    keep_set = set(keep_cols)
    if always_keep:
        keep_set.add(always_keep)

    return [{k: v for k, v in row.items() if k in keep_set} for row in rows]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _iter_hours(start: datetime, end: datetime):
    current = start.replace(minute=0, second=0, microsecond=0)
    while current <= end:
        hour_end = current.replace(minute=59, second=59)
        yield current, hour_end
        current += timedelta(hours=1)

