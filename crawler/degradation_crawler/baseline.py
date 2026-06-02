"""
baseline.py — Phase 1: Build the healthy baseline for each turbine.

Crawls the first BASELINE_MONTHS months of operation for a turbine (assumed
healthy), groups every hour into a 3-D operating condition bin
(wind × power × ambient), accumulates temperature readings, then stores the
per-bin mean in a SQLite database.

Any subsequent ΔT residual is measured against these stored means.

Usage (called from run.py):
    from degradation_crawler.baseline import build_baseline
    build_baseline(
        farm="kelmarsh",
        turbine="turbine_2",
        start_date=date(2016, 5, 1),
        end_date=date(2017, 5, 31),
        mask_windows=[],           # list of (start_date, end_date) to skip
    )
"""

from __future__ import annotations

import sqlite3
import statistics
import time
from collections import defaultdict
from datetime import date, timedelta
from typing import Optional

import requests

from .bins import get_bin
from .config import (
    API_BASE,
    BASELINE_DB,
    COND_COLS,
    MIN_BIN_OBS,
    MIN_ROWS_PER_HOUR,
    TEMP_COLS,
    TEMP_RANGE,
)
from .machine_logger import log


# ---------------------------------------------------------------------------
# SQLite helpers
# ---------------------------------------------------------------------------

def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS baseline (
            farm    TEXT NOT NULL,
            turbine TEXT NOT NULL,
            bin     TEXT NOT NULL,
            col     TEXT NOT NULL,
            mean    REAL NOT NULL,
            std     REAL,           -- stddev of observations (used in sigma-exceedance criterion)
            n       INTEGER NOT NULL,
            PRIMARY KEY (farm, turbine, bin, col)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS baseline_meta (
            farm        TEXT NOT NULL,
            turbine     TEXT NOT NULL,
            start_date  TEXT NOT NULL,
            end_date    TEXT NOT NULL,
            built_at    TEXT NOT NULL,
            total_hours INTEGER,
            bins_stored INTEGER,
            PRIMARY KEY (farm, turbine)
        )
    """)
    conn.commit()


def load_baseline(farm: str, turbine: str, db_path=BASELINE_DB) -> dict[str, dict[str, float]]:
    """
    Load the baseline from SQLite into an in-memory dict:
        {bin_key: {col: mean_temp}}

    Returns an empty dict if no baseline exists for this turbine.
    """
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT bin, col, mean FROM baseline WHERE farm=? AND turbine=?",
        (farm, turbine),
    ).fetchall()
    conn.close()

    baseline: dict[str, dict[str, float]] = defaultdict(dict)
    for bin_key, col, mean in rows:
        baseline[bin_key][col] = mean
    return dict(baseline)


def load_baseline_std(farm: str, turbine: str, db_path=BASELINE_DB) -> dict[str, dict[str, Optional[float]]]:
    """Load per-bin per-col std values for sigma-exceedance scoring."""
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT bin, col, std FROM baseline WHERE farm=? AND turbine=?",
        (farm, turbine),
    ).fetchall()
    conn.close()

    result: dict[str, dict[str, Optional[float]]] = defaultdict(dict)
    for bin_key, col, std in rows:
        result[bin_key][col] = std
    return dict(result)


def baseline_exists(farm: str, turbine: str, db_path=BASELINE_DB) -> bool:
    """Return True if at least one bin is stored for this turbine."""
    conn = sqlite3.connect(db_path)
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM baseline WHERE farm=? AND turbine=?", (farm, turbine)
        ).fetchone()[0]
    except sqlite3.OperationalError:
        # Table doesn't exist yet — no baseline built
        n = 0
    finally:
        conn.close()
    return n > 0


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def _fetch_hour(
    session: requests.Session,
    farm: str,
    turbine: str,
    day: str,      # "YYYY-MM-DD"
    hour: int,
    columns: list[str],
    retries: int = 3,
) -> Optional[dict]:
    """
    Fetch one hour of SCADA data from the live wind data API.

    Real API: GET /wind-farms/{farm}/data/{date}
              ?turbine=T&columns[]=C&hour_from=H&hour_to=H

    Returns the parsed JSON response (with 'columns' list and 'rows' list-of-lists),
    or None on failure / too few rows.
    """
    url = f"{API_BASE}/wind-farms/{farm}/data/{day}"
    # Build params — requests will repeat 'columns[]' for each column
    params: list[tuple] = [
        ("turbine", turbine),
        ("hour_from", hour),
        ("hour_to", hour),
    ]
    for col in columns:
        params.append(("columns[]", col))

    for attempt in range(retries):
        try:
            resp = session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if not data or len(data.get("rows", [])) < MIN_ROWS_PER_HOUR:
                return None
            return data
        except Exception as exc:
            log("WARN", "api_retry", farm=farm, turbine=turbine,
                day=day, hour=hour, attempt=attempt + 1, error=str(exc))
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    return None


def _col_values(data: dict, col: str) -> list[float]:
    """
    Extract validated numeric values for *col* from an API response.

    The API returns rows as positional arrays aligned to data["columns"],
    so we first resolve the column index, then read each row by position.
    """
    col_names: list[str] = data.get("columns", [])
    try:
        idx = col_names.index(col)
    except ValueError:
        return []   # column not in this response

    lo, hi = TEMP_RANGE
    values = []
    for row in data.get("rows", []):
        if idx >= len(row):
            continue
        v = row[idx]
        if v is None:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        # Reject physical outliers only for temperature columns
        if col in TEMP_COLS and not (lo <= fv <= hi):
            continue
        values.append(fv)
    return values


def _safe_mean(values: list[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def _safe_std(values: list[float]) -> Optional[float]:
    return statistics.pstdev(values) if len(values) >= 2 else None


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def build_baseline(
    farm: str,
    turbine: str,
    start_date: date,
    end_date: date,
    mask_windows: list[tuple[date, date]],
    db_path=BASELINE_DB,
) -> dict:
    """
    Phase 1 — Build T_baseline[bin][col] for a single turbine.

    Crawls every day from start_date to end_date, skips masked maintenance
    windows, accumulates temperature readings per operating-condition bin,
    then persists per-bin means to SQLite.

    Returns a summary dict:
        {bins_stored, hours_processed, hours_skipped_mask, hours_skipped_data}
    """
    log("INFO", "baseline_start", farm=farm, turbine=turbine,
        start=str(start_date), end=str(end_date))

    BASELINE_DB.parent.mkdir(parents=True, exist_ok=True)

    all_cols = TEMP_COLS + COND_COLS
    session = requests.Session()

    # bin_accum: bin_key → {col → [values]}
    bin_accum: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))

    hours_processed = 0
    hours_skipped_mask = 0
    hours_skipped_data = 0

    d = start_date
    while d <= end_date:
        # Skip masked maintenance windows
        if _is_masked(d, mask_windows):
            hours_skipped_mask += 24
            d += timedelta(days=1)
            continue

        for hour in range(24):
            data = _fetch_hour(session, farm, turbine, d.isoformat(), hour, all_cols)
            if data is None:
                hours_skipped_data += 1
                continue

            # Extract conditioning variables
            wind    = _safe_mean(_col_values(data, "Wind speed (m/s)"))
            power   = _safe_mean(_col_values(data, "Power (kW)"))
            ambient = _safe_mean(_col_values(data, "Nacelle ambient temperature (°C)"))

            if any(v is None for v in [wind, power, ambient]):
                hours_skipped_data += 1
                continue

            bin_key = get_bin(wind, power, ambient)  # type: ignore[arg-type]

            # Accumulate temperature readings
            for col in TEMP_COLS:
                vals = _col_values(data, col)
                if vals:
                    bin_accum[bin_key][col].extend(vals)

            hours_processed += 1

        d += timedelta(days=1)

    # Persist to SQLite
    conn = sqlite3.connect(db_path)
    _ensure_schema(conn)

    bins_stored = 0
    for bin_key, cols in bin_accum.items():
        for col, vals in cols.items():
            if len(vals) >= MIN_BIN_OBS:
                conn.execute(
                    "INSERT OR REPLACE INTO baseline VALUES (?,?,?,?,?,?,?)",
                    (
                        farm, turbine, bin_key, col,
                        _safe_mean(vals),
                        _safe_std(vals),
                        len(vals),
                    ),
                )
                bins_stored += 1

    conn.execute(
        "INSERT OR REPLACE INTO baseline_meta VALUES (?,?,?,?,?,?,?)",
        (
            farm, turbine,
            str(start_date), str(end_date),
            _now_utc(),
            hours_processed,
            bins_stored,
        ),
    )
    conn.commit()
    conn.close()

    summary = {
        "bins_stored": bins_stored,
        "hours_processed": hours_processed,
        "hours_skipped_mask": hours_skipped_mask,
        "hours_skipped_data": hours_skipped_data,
    }
    log("INFO", "baseline_built", farm=farm, turbine=turbine, **summary)
    return summary


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_masked(d: date, windows: list[tuple[date, date]]) -> bool:
    for start, end in windows:
        if start <= d <= end:
            return True
    return False


def _now_utc() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

