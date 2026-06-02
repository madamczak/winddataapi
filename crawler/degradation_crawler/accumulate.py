"""
accumulate.py — Cross-temporal data collection phase (used by --mode trend).

Instead of splitting data into baseline vs. scan periods, this module crawls
the ENTIRE available date range for a turbine (e.g. 2016-2020) and stores
every valid hourly observation in a SQLite database, keyed by operating
condition bin.

Key difference from baseline.py:
  - One API call per day  (hour_from=0, hour_to=23) instead of 24
  - ALL temperature readings stored — not just means for the baseline period
  - Resumable: crawl_progress table tracks which days have been committed

The stored observations feed trend_analysis.py which fits an OLS linear
regression of temperature vs. time per (bin, col), producing a slope in
°C/year — the actual degradation signal.

Usage:
    from degradation_crawler.accumulate import accumulate_turbine
    accumulate_turbine(
        farm="kelmarsh", turbine="turbine_2",
        data_start=date(2016, 6, 8), data_end=date(2020, 12, 31),
    )
"""

from __future__ import annotations

import sqlite3
import time
from collections import defaultdict
from datetime import date, timedelta
from typing import Optional

import requests

from .bins import get_bin
from .config import (
    API_BASE,
    COND_COLS,
    MIN_ROWS_PER_HOUR,
    TEMP_COLS,
    TEMP_RANGE,
    TREND_DB,
)
from .machine_logger import log


# ---------------------------------------------------------------------------
# SQLite schema
# ---------------------------------------------------------------------------

def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS observations (
            farm        TEXT NOT NULL,
            turbine     TEXT NOT NULL,
            date        TEXT NOT NULL,
            hour        INTEGER NOT NULL,
            bin         TEXT NOT NULL,
            col         TEXT NOT NULL,
            value       REAL NOT NULL,
            ordinal_day INTEGER NOT NULL,
            PRIMARY KEY (farm, turbine, date, hour, bin, col)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_obs_turbine_bin_col
            ON observations (farm, turbine, bin, col)
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS crawl_progress (
            farm        TEXT NOT NULL,
            turbine     TEXT NOT NULL,
            date        TEXT NOT NULL,
            rows_stored INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (farm, turbine, date)
        )
    """)
    conn.commit()


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def accumulate_turbine(
    farm: str,
    turbine: str,
    data_start: date,
    data_end: date,
    db_path=TREND_DB,
) -> dict:
    """
    Crawl the full date range for one turbine, storing every valid hourly
    observation to SQLite.

    Returns a summary dict:
        {days_fetched, days_skipped_api, days_skipped_progress,
         rows_stored, rows_skipped}
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    _ensure_schema(conn)

    session = requests.Session()
    all_cols = TEMP_COLS + COND_COLS

    days_fetched = 0
    days_skipped_api = 0
    days_skipped_progress = 0
    rows_stored = 0
    rows_skipped = 0

    pending = _pending_dates(conn, farm, turbine, data_start, data_end)
    log("INFO", "accumulate_start", farm=farm, turbine=turbine,
        pending_days=len(pending),
        start=str(data_start), end=str(data_end))

    batch_rows: list[tuple] = []
    batch_days: list[str] = []

    for day in pending:
        day_str = day.isoformat()
        data = _fetch_day(session, farm, turbine, day_str, retries=3)
        if data is None:
            days_skipped_api += 1
            # Still mark as processed so we don't retry empty days forever
            batch_days.append(day_str)
            _maybe_commit_batch(conn, farm, turbine, batch_rows, batch_days)
            batch_rows = []
            batch_days = []
            continue

        hourly = _group_by_hour(data, all_cols)
        day_rows_stored = 0
        day_rows_skipped = 0

        for hour, col_vals in hourly.items():
            # Need conditioning variables to assign a bin
            wind_vals   = col_vals.get("Wind speed (m/s)", [])
            power_vals  = col_vals.get("Power (kW)", [])
            ambient_vals = col_vals.get("Nacelle ambient temperature (°C)", [])

            if not wind_vals or not power_vals or not ambient_vals:
                day_rows_skipped += 1
                continue

            if (len(wind_vals) < MIN_ROWS_PER_HOUR or
                    len(power_vals) < MIN_ROWS_PER_HOUR or
                    len(ambient_vals) < MIN_ROWS_PER_HOUR):
                day_rows_skipped += 1
                continue

            wind    = sum(wind_vals) / len(wind_vals)
            power   = sum(power_vals) / len(power_vals)
            ambient = sum(ambient_vals) / len(ambient_vals)
            bin_key = get_bin(wind, power, ambient)
            ordinal = day.toordinal()

            for col in TEMP_COLS:
                vals = col_vals.get(col, [])
                if len(vals) < MIN_ROWS_PER_HOUR:
                    continue
                mean_val = sum(vals) / len(vals)
                batch_rows.append(
                    (farm, turbine, day_str, hour, bin_key, col, mean_val, ordinal)
                )
                day_rows_stored += 1

        rows_stored += day_rows_stored
        rows_skipped += day_rows_skipped
        days_fetched += 1
        batch_days.append(day_str)

        # Commit every 30 days (resume-boundary)
        if len(batch_days) >= 30:
            _maybe_commit_batch(conn, farm, turbine, batch_rows, batch_days)
            batch_rows = []
            batch_days = []
            log("DEBUG", "accumulate_progress", farm=farm, turbine=turbine,
                days_done=days_fetched, rows_stored=rows_stored)

    # Commit remaining
    if batch_days:
        _maybe_commit_batch(conn, farm, turbine, batch_rows, batch_days)

    conn.close()

    summary = {
        "days_fetched": days_fetched,
        "days_skipped_api": days_skipped_api,
        "days_skipped_progress": days_skipped_progress,
        "rows_stored": rows_stored,
        "rows_skipped": rows_skipped,
    }
    log("INFO", "accumulate_done", farm=farm, turbine=turbine, **summary)
    return summary


def is_accumulated(farm: str, turbine: str, db_path=TREND_DB) -> bool:
    """Return True if any observations exist for this turbine."""
    if not db_path.exists():
        return False
    conn = sqlite3.connect(db_path)
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM observations WHERE farm=? AND turbine=?",
            (farm, turbine)
        ).fetchone()[0]
    except sqlite3.OperationalError:
        n = 0
    finally:
        conn.close()
    return n > 0


def pending_day_count(
    farm: str,
    turbine: str,
    data_start: date,
    data_end: date,
    db_path=TREND_DB,
) -> int:
    """Return the number of days in [data_start, data_end] not yet crawled."""
    if not db_path.exists():
        total = (data_end - data_start).days + 1
        return total
    conn = sqlite3.connect(db_path)
    try:
        pending = _pending_dates(conn, farm, turbine, data_start, data_end)
    except Exception:
        pending = []
    finally:
        conn.close()
    return len(pending)


def observation_count(farm: str, turbine: str, db_path=TREND_DB) -> int:
    """Return total observation rows stored for this turbine."""
    if not db_path.exists():
        return 0
    conn = sqlite3.connect(db_path)
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM observations WHERE farm=? AND turbine=?",
            (farm, turbine)
        ).fetchone()[0]
    except sqlite3.OperationalError:
        n = 0
    finally:
        conn.close()
    return n


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _pending_dates(
    conn: sqlite3.Connection,
    farm: str,
    turbine: str,
    data_start: date,
    data_end: date,
) -> list[date]:
    """Return dates in [data_start, data_end] not yet in crawl_progress."""
    try:
        done = {
            row[0]
            for row in conn.execute(
                "SELECT date FROM crawl_progress WHERE farm=? AND turbine=?",
                (farm, turbine),
            ).fetchall()
        }
    except sqlite3.OperationalError:
        done = set()

    days = []
    d = data_start
    while d <= data_end:
        if d.isoformat() not in done:
            days.append(d)
        d += timedelta(days=1)
    return days


def _fetch_day(
    session: requests.Session,
    farm: str,
    turbine: str,
    day: str,        # "YYYY-MM-DD"
    retries: int = 3,
) -> Optional[dict]:
    """
    Fetch all hours of a day in a single API call.

    GET /wind-farms/{farm}/data/{day}?turbine=T&hour_from=0&hour_to=23

    Returns the raw API response dict, or None on failure / no data.
    """
    url = f"{API_BASE}/wind-farms/{farm}/data/{day}"
    params = [
        ("turbine", turbine),
        ("hour_from", 0),
        ("hour_to",   23),
    ]

    for attempt in range(retries):
        try:
            resp = session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            # Need at least a few full hours of data
            if not data or data.get("row_count", 0) < MIN_ROWS_PER_HOUR * 4:
                return None
            return data
        except Exception as exc:
            log("WARN", "accumulate_fetch_retry", farm=farm, turbine=turbine,
                day=day, attempt=attempt + 1, error=str(exc))
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    return None


def _group_by_hour(
    data: dict,
    all_cols: list[str],
) -> dict[int, dict[str, list[float]]]:
    """
    Group all rows in an API response by hour, returning per-col float lists.

    data["columns"] is the positional column list.
    data["rows"] is a list of positional arrays.

    Returns {hour: {col_name: [valid_float_values]}}
    """
    col_names: list[str] = data.get("columns", [])

    # Resolve column indices once
    dt_idx: Optional[int] = None
    col_indices: dict[str, int] = {}
    for c in all_cols:
        try:
            col_indices[c] = col_names.index(c)
        except ValueError:
            pass
    try:
        dt_idx = col_names.index("Date and time")
    except ValueError:
        return {}  # can't group without timestamps

    lo, hi = TEMP_RANGE
    hourly: dict[int, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))

    for row in data.get("rows", []):
        if dt_idx >= len(row) or row[dt_idx] is None:
            continue
        try:
            # "2018-04-12 14:30:00" → hour 14
            hour = int(str(row[dt_idx])[11:13])
        except (ValueError, IndexError):
            continue

        for col, idx in col_indices.items():
            if idx >= len(row):
                continue
            v = row[idx]
            if v is None:
                continue
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            # Range check only for temperature columns
            if col in TEMP_COLS and not (lo <= fv <= hi):
                continue
            hourly[hour][col].append(fv)

    return {h: dict(cols) for h, cols in hourly.items()}


def _maybe_commit_batch(
    conn: sqlite3.Connection,
    farm: str,
    turbine: str,
    rows: list[tuple],
    days: list[str],
) -> None:
    """Commit a batch of observation rows and mark their days as done."""
    if rows:
        conn.executemany(
            """INSERT OR IGNORE INTO observations
               (farm, turbine, date, hour, bin, col, value, ordinal_day)
               VALUES (?,?,?,?,?,?,?,?)""",
            rows,
        )
    for day_str in days:
        conn.execute(
            """INSERT OR IGNORE INTO crawl_progress (farm, turbine, date, rows_stored)
               VALUES (?,?,?,?)""",
            (farm, turbine, day_str, sum(1 for r in rows if r[2] == day_str)),
        )
    conn.commit()

