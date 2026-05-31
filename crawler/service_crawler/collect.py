"""
collect.py — Phase B: Collect pre/post window data for each service event.

For every pending service event, this module fetches hourly turbine data for:
  - PRE  window: [event_start − WINDOW_DAYS, event_start − 1 day]
  - POST window: [event_end + 1 day,          event_end + WINDOW_DAYS]

Each valid hourly observation is assigned an operating condition bin and
stored in the window_observations table.  Once a full event's pre + post
windows are collected, the event is marked as crawled.

Usage:
    from service_crawler.collect import collect_event_windows
    collect_event_windows(farm="kelmarsh", turbine="turbine_2", events=[...])
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
    DB_PATH,
    MIN_ROWS_PER_HOUR,
    TEMP_COLS,
    TEMP_RANGE,
    WINDOW_DAYS,
)
from .fetch_events import mark_event_crawled
from .logger import log


# ---------------------------------------------------------------------------
# SQLite schema
# ---------------------------------------------------------------------------

def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS window_observations (
            farm      TEXT NOT NULL,
            turbine   TEXT NOT NULL,
            event_id  TEXT NOT NULL,
            phase     TEXT NOT NULL,   -- 'pre' or 'post'
            date      TEXT NOT NULL,
            hour      INTEGER NOT NULL,
            bin       TEXT NOT NULL,
            col       TEXT NOT NULL,
            value     REAL NOT NULL,
            PRIMARY KEY (farm, turbine, event_id, phase, date, hour, bin, col)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_wobs_event
            ON window_observations (farm, turbine, event_id, phase)
    """)
    conn.commit()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def collect_event_windows(
    farm: str,
    turbine: str,
    events: list[dict],
    db_path=DB_PATH,
    window_days: int = WINDOW_DAYS,
) -> dict:
    """
    For each event in *events*, collect pre and post window data.

    Each event dict must have: event_id, event_start (ISO date str),
    event_end (ISO date str).

    Returns a summary dict:
        {events_processed, events_skipped, total_obs_stored}
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    _ensure_schema(conn)

    session = requests.Session()
    all_cols = TEMP_COLS + COND_COLS

    events_processed = 0
    events_skipped   = 0
    total_obs_stored = 0

    for ev in events:
        event_id   = ev["event_id"]
        ev_start   = date.fromisoformat(ev["event_start"])
        ev_end     = date.fromisoformat(ev["event_end"])

        pre_start  = ev_start - timedelta(days=window_days)
        pre_end    = ev_start - timedelta(days=1)
        post_start = ev_end   + timedelta(days=1)
        post_end   = ev_end   + timedelta(days=window_days)

        log("INFO", "collect_event_start",
            farm=farm, turbine=turbine, event_id=event_id,
            event_start=str(ev_start), event_end=str(ev_end),
            pre_start=str(pre_start), post_end=str(post_end))

        obs_stored = 0

        # Collect PRE window
        obs_stored += _collect_window(
            conn, session, farm, turbine, event_id,
            phase="pre",
            start=pre_start,
            end=pre_end,
            all_cols=all_cols,
        )

        # Collect POST window
        obs_stored += _collect_window(
            conn, session, farm, turbine, event_id,
            phase="post",
            start=post_start,
            end=post_end,
            all_cols=all_cols,
        )

        total_obs_stored += obs_stored
        if obs_stored > 0:
            events_processed += 1
        else:
            events_skipped += 1
            log("WARN", "collect_event_no_data",
                farm=farm, turbine=turbine, event_id=event_id)

        # Mark event as crawled regardless (avoid infinite retry on empty data)
        mark_event_crawled(farm, turbine, event_id, db_path)

        log("INFO", "collect_event_done",
            farm=farm, turbine=turbine, event_id=event_id,
            obs_stored=obs_stored)

    conn.close()
    return {
        "events_processed": events_processed,
        "events_skipped":   events_skipped,
        "total_obs_stored": total_obs_stored,
    }


def observation_counts(
    farm: str,
    turbine: str,
    event_id: str,
    db_path=DB_PATH,
) -> dict[str, int]:
    """Return {phase: n_observations} for a given event."""
    if not db_path.exists():
        return {"pre": 0, "post": 0}
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """SELECT phase, COUNT(*) FROM window_observations
               WHERE farm=? AND turbine=? AND event_id=?
               GROUP BY phase""",
            (farm, turbine, event_id),
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    finally:
        conn.close()
    result = {"pre": 0, "post": 0}
    for phase, n in rows:
        result[phase] = n
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _collect_window(
    conn: sqlite3.Connection,
    session: requests.Session,
    farm: str,
    turbine: str,
    event_id: str,
    phase: str,
    start: date,
    end: date,
    all_cols: list[str],
) -> int:
    """
    Fetch and store all valid hourly observations for [start, end].
    Returns the number of (bin, col) observation rows stored.
    """
    obs_stored = 0
    d = start
    while d <= end:
        day_str = d.isoformat()
        data = _fetch_day(session, farm, turbine, day_str, retries=3)
        if data is None:
            d += timedelta(days=1)
            continue

        hourly = _group_by_hour(data, all_cols)
        batch: list[tuple] = []

        for hour, col_vals in hourly.items():
            wind_vals    = col_vals.get("Wind speed (m/s)", [])
            power_vals   = col_vals.get("Power (kW)", [])
            ambient_vals = col_vals.get("Nacelle ambient temperature (°C)", [])

            if (len(wind_vals) < MIN_ROWS_PER_HOUR or
                    len(power_vals) < MIN_ROWS_PER_HOUR or
                    len(ambient_vals) < MIN_ROWS_PER_HOUR):
                continue

            wind    = sum(wind_vals)    / len(wind_vals)
            power   = sum(power_vals)   / len(power_vals)
            ambient = sum(ambient_vals) / len(ambient_vals)
            bin_key = get_bin(wind, power, ambient)

            for col in TEMP_COLS:
                vals = col_vals.get(col, [])
                if len(vals) < MIN_ROWS_PER_HOUR:
                    continue
                mean_val = sum(vals) / len(vals)
                batch.append(
                    (farm, turbine, event_id, phase,
                     day_str, hour, bin_key, col, mean_val)
                )

        if batch:
            conn.executemany(
                """INSERT OR IGNORE INTO window_observations
                   (farm, turbine, event_id, phase, date, hour, bin, col, value)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                batch,
            )
            conn.commit()
            obs_stored += len(batch)

        d += timedelta(days=1)

    return obs_stored


def _fetch_day(
    session: requests.Session,
    farm: str,
    turbine: str,
    day: str,
    retries: int = 3,
) -> Optional[dict]:
    """
    Fetch all hours of a day in a single API call.
    GET /wind-farms/{farm}/data/{day}?turbine=T&hour_from=0&hour_to=23
    Returns the raw API response dict or None on failure.
    """
    url = f"{API_BASE}/wind-farms/{farm}/data/{day}"
    params = [
        ("turbine",   turbine),
        ("hour_from", 0),
        ("hour_to",   23),
    ]
    for attempt in range(retries):
        try:
            resp = session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if not data or data.get("row_count", 0) < MIN_ROWS_PER_HOUR * 2:
                return None
            return data
        except Exception as exc:
            log("WARN", "collect_fetch_retry",
                farm=farm, turbine=turbine, day=day,
                attempt=attempt + 1, error=str(exc))
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
        return {}

    lo, hi = TEMP_RANGE
    hourly: dict[int, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))

    for row in data.get("rows", []):
        if dt_idx >= len(row) or row[dt_idx] is None:
            continue
        try:
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
            if col in TEMP_COLS and not (lo <= fv <= hi):
                continue
            hourly[hour][col].append(fv)

    return {h: dict(cols) for h, cols in hourly.items()}

