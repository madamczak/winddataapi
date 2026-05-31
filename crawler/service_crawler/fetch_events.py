"""
fetch_events.py — Phase A: Fetch and persist scheduled maintenance events.

Queries the wind data API for all IEC "Scheduled Maintenance" events on a
turbine and stores them in the service_events table of service_crawler.db.

The table tracks crawl status so Phase B can pick up only uncrawled events.

Usage:
    from service_crawler.fetch_events import fetch_and_store_events
    events = fetch_and_store_events(
        farm="kelmarsh", turbine="turbine_2",
        data_start=date(2016, 6, 8), data_end=date(2020, 12, 31),
    )
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from datetime import date

import requests

from .config import API_BASE, DB_PATH, SCHEDULED_MAINTENANCE_CATEGORY
from .logger import log


# ---------------------------------------------------------------------------
# SQLite schema
# ---------------------------------------------------------------------------

def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS service_events (
            farm          TEXT NOT NULL,
            turbine       TEXT NOT NULL,
            event_id      TEXT NOT NULL,   -- deterministic hash of farm|turbine|start
            event_start   TEXT NOT NULL,   -- ISO date "YYYY-MM-DD"
            event_end     TEXT NOT NULL,   -- ISO date "YYYY-MM-DD"
            duration_days INTEGER NOT NULL,
            crawled       INTEGER NOT NULL DEFAULT 0,  -- 0=pending, 1=done
            PRIMARY KEY (farm, turbine, event_id)
        )
    """)
    conn.commit()


def _make_event_id(farm: str, turbine: str, event_start: str) -> str:
    """Stable, short event identifier derived from farm + turbine + start date."""
    raw = f"{farm}|{turbine}|{event_start}"
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_and_store_events(
    farm: str,
    turbine: str,
    data_start: date,
    data_end: date,
    db_path=DB_PATH,
    retries: int = 3,
) -> list[dict]:
    """
    Fetch all Scheduled Maintenance events from the API for the given turbine
    and date range, persist them (INSERT OR IGNORE), and return a list of
    event dicts.

    Each dict has keys: event_id, farm, turbine, event_start, event_end,
    duration_days, crawled.

    Returns only events whose event_start falls within [data_start, data_end].
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    _ensure_schema(conn)

    # ── Hit the API ──────────────────────────────────────────────────────────
    session = requests.Session()
    url = f"{API_BASE}/wind-farms/{farm}/{turbine}/events"
    params: dict = {"limit": 5000}
    raw_events: list[dict] = []

    for attempt in range(retries):
        try:
            resp = session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            payload = resp.json()
            raw_events = payload.get("events", [])
            break
        except Exception as exc:
            log("WARN", "fetch_events_retry",
                farm=farm, turbine=turbine,
                attempt=attempt + 1, error=str(exc))
            if attempt < retries - 1:
                time.sleep(2 ** attempt)

    if not raw_events:
        log("INFO", "fetch_events_empty", farm=farm, turbine=turbine)
        conn.close()
        return []

    # ── Filter to Scheduled Maintenance and date range ────────────────────
    stored = 0
    events_out: list[dict] = []

    for ev in raw_events:
        category = str(ev.get("IEC category", ""))
        if category != SCHEDULED_MAINTENANCE_CATEGORY:
            continue

        try:
            ev_start = date.fromisoformat(str(ev["Timestamp start"])[:10])
            ts_end = ev.get("Timestamp end") or ev.get("Timestamp start")
            ev_end = date.fromisoformat(str(ts_end)[:10])
        except (KeyError, ValueError):
            continue

        # Enforce data range filter
        if ev_start < data_start or ev_start > data_end:
            continue
        # Clamp end date to data_end
        ev_end = min(ev_end, data_end)

        duration_days = max((ev_end - ev_start).days, 1)
        event_id = _make_event_id(farm, turbine, str(ev_start))

        conn.execute(
            """INSERT OR IGNORE INTO service_events
               (farm, turbine, event_id, event_start, event_end, duration_days, crawled)
               VALUES (?,?,?,?,?,?,0)""",
            (farm, turbine, event_id,
             str(ev_start), str(ev_end), duration_days),
        )
        stored += 1

        events_out.append({
            "event_id":     event_id,
            "farm":         farm,
            "turbine":      turbine,
            "event_start":  str(ev_start),
            "event_end":    str(ev_end),
            "duration_days": duration_days,
        })

    conn.commit()
    conn.close()

    log("INFO", "fetch_events_done",
        farm=farm, turbine=turbine,
        raw_events=len(raw_events),
        maintenance_events=len(events_out),
        stored_new=stored)

    return events_out


def load_pending_events(
    farm: str,
    turbine: str,
    db_path=DB_PATH,
) -> list[dict]:
    """
    Return all service_events for this turbine where crawled=0.
    Returns a list of dicts with keys: event_id, event_start, event_end,
    duration_days.
    """
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """SELECT event_id, event_start, event_end, duration_days
               FROM service_events
               WHERE farm=? AND turbine=? AND crawled=0
               ORDER BY event_start""",
            (farm, turbine),
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    finally:
        conn.close()

    return [
        {"event_id": r[0], "event_start": r[1], "event_end": r[2], "duration_days": r[3]}
        for r in rows
    ]


def load_all_events(
    farm: str,
    turbine: str,
    db_path=DB_PATH,
) -> list[dict]:
    """Return all service_events for this turbine, regardless of crawl status."""
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """SELECT event_id, event_start, event_end, duration_days, crawled
               FROM service_events
               WHERE farm=? AND turbine=?
               ORDER BY event_start""",
            (farm, turbine),
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    finally:
        conn.close()

    return [
        {
            "event_id": r[0], "event_start": r[1], "event_end": r[2],
            "duration_days": r[3], "crawled": bool(r[4]),
        }
        for r in rows
    ]


def mark_event_crawled(
    farm: str,
    turbine: str,
    event_id: str,
    db_path=DB_PATH,
) -> None:
    """Mark a service event as crawled (crawled=1) in the DB."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE service_events SET crawled=1 WHERE farm=? AND turbine=? AND event_id=?",
        (farm, turbine, event_id),
    )
    conn.commit()
    conn.close()


