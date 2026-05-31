"""
service_mask.py — Phase 3: Fetch maintenance/repair events and build mask windows.

The API returns status/event records with IEC categories. We collect windows
around maintenance events to exclude them from baseline and scan phases,
preventing planned work from distorting the temperature signal.

IEC event categories we mask:
    "M" — scheduled maintenance
    "R" — repair (unscheduled)
    "T" — scheduled test / commissioning

A configurable padding (MASK_PADDING_DAYS) is added on each side of an event
window because temperatures often deviate before and after physical work:
  - Before: technicians may have run the turbine in a special mode
  - After:  new parts need a run-in period (oil, bearings heat differently)

Usage:
    from degradation_crawler.service_mask import fetch_mask_windows, is_masked

    windows = fetch_mask_windows(farm="kelmarsh", turbine="turbine_2")
    if is_masked(some_date, windows):
        ...  # skip this day
"""

from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Optional

import requests

from .config import API_BASE
from .machine_logger import log

# Number of calendar days to add before and after each service event.
# This prevents run-in / run-out temperature artifacts from corrupting the signal.
MASK_PADDING_DAYS: int = 3

# IEC event category strings (full names as returned by the API) that should be masked.
# The API uses: "Scheduled Maintenance", "Forced outage", "Requested Shutdown"
MASKED_IEC_CATEGORIES: set[str] = {
    "Scheduled Maintenance",
    "Forced outage",
    "Requested Shutdown",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_mask_windows(
    farm: str,
    turbine: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    retries: int = 3,
) -> list[tuple[date, date]]:
    """
    Query the wind data API for service events and return a list of
    (mask_start, mask_end) date tuples to be excluded from analysis.

    Includes MASK_PADDING_DAYS on each side of each raw event window.
    Overlapping windows are automatically merged.

    Parameters
    ----------
    farm, turbine : str
        Target turbine identifier.
    start_date, end_date : date, optional
        Limit query to this date range (both inclusive). If omitted, all
        events for the turbine are returned.
    retries : int
        HTTP retry count on transient failures.

    Returns
    -------
    list of (date, date) tuples, sorted by start date, non-overlapping.
    """
    # Real API: GET /wind-farms/{farm}/{turbine}/events?limit=...
    # The iec_category query param causes 422 for multi-word values, so we fetch
    # all events and filter client-side by "IEC category" field.
    session = requests.Session()
    raw_events: list[dict] = []
    url = f"{API_BASE}/wind-farms/{farm}/{turbine}/events"
    params: dict = {"limit": 5000}

    for attempt in range(retries):
        try:
            resp = session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            payload = resp.json()
            # Response: {farm, turbine, columns: [...], events: [{...}], count: N}
            raw_events = payload.get("events", [])
            break
        except Exception as exc:
            log("WARN", "service_mask_fetch_retry",
                farm=farm, turbine=turbine,
                attempt=attempt + 1, error=str(exc))
            if attempt < retries - 1:
                time.sleep(2 ** attempt)

    if not raw_events:
        log("INFO", "service_mask_empty", farm=farm, turbine=turbine,
            note="No service events found — nothing masked.")
        return []

    # Filter to relevant IEC categories and extract date ranges
    raw_windows: list[tuple[date, date]] = []
    for event in raw_events:
        # API field is "IEC category" (full string), not short code
        category = str(event.get("IEC category", ""))
        if category not in MASKED_IEC_CATEGORIES:
            continue
        try:
            ev_start = date.fromisoformat(str(event["Timestamp start"])[:10])
            ts_end = event.get("Timestamp end") or event.get("Timestamp start")
            ev_end = date.fromisoformat(str(ts_end)[:10])
        except (KeyError, ValueError):
            continue

        padded_start = ev_start - timedelta(days=MASK_PADDING_DAYS)
        padded_end   = ev_end   + timedelta(days=MASK_PADDING_DAYS)
        raw_windows.append((padded_start, padded_end))

    merged = _merge_windows(raw_windows)
    log("INFO", "service_mask_built", farm=farm, turbine=turbine,
        raw_events=len(raw_events), windows=len(merged))
    return merged


def is_masked(d: date, windows: list[tuple[date, date]]) -> bool:
    """
    Return True if *d* falls inside any mask window.

    Uses sequential scan; for large window lists consider bisect-based lookup.
    """
    for start, end in windows:
        if start <= d <= end:
            return True
    return False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _merge_windows(windows: list[tuple[date, date]]) -> list[tuple[date, date]]:
    """Merge overlapping or adjacent date windows into disjoint intervals."""
    if not windows:
        return []
    sorted_wins = sorted(windows, key=lambda w: w[0])
    merged = [sorted_wins[0]]
    for start, end in sorted_wins[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end + timedelta(days=1):
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged

