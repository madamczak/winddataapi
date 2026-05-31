"""
analysis.py — Phase C: Delta analysis comparing pre vs. post service data.

For each (event, operating-condition bin, temperature column), this module:

  1. Loads all PRE observations: hourly mean temperatures in the 7-day window
     before the service.
  2. Loads all POST observations: hourly mean temperatures in the 7-day window
     after the service.
  3. For each (bin, col) pair that has at least MIN_OBS_PER_PHASE observations
     in BOTH the pre and post windows:
         delta = mean_post − mean_pre
     A **negative** delta → turbine ran cooler after the service (expected).
     A **positive** delta → turbine ran hotter after the service (investigate).
  4. Assigns a severity label and persists the ServiceDelta to service_crawler.db.

Usage:
    from service_crawler.analysis import analyse_event, analyse_turbine
    deltas = analyse_turbine(farm="kelmarsh", turbine="turbine_2")
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from .config import (
    DB_PATH,
    DELTA_IMPROVED,
    DELTA_SLIGHT_DECLINE,
    DELTA_SLIGHT_IMPROVEMENT,
    DELTA_WORSENED,
    MIN_OBS_PER_PHASE,
    TEMP_COLS,
)
from .logger import log


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ServiceDelta:
    """
    Comparison result for one service event / operating-condition bin / sensor.

    Severity semantics:
        IMPROVED          delta ≤ −3.0 °C   — clear thermal improvement
        SLIGHT_IMPROVEMENT −3.0 < delta ≤ −1.0
        NEUTRAL            −1.0 < delta < +1.0
        SLIGHT_DECLINE     +1.0 ≤ delta < +3.0
        WORSENED           delta ≥ +3.0 °C  — hotter after service, investigate
    """
    farm:         str
    turbine:      str
    event_id:     str
    event_start:  str
    event_end:    str
    bin:          str
    col:          str
    mean_pre:     float
    std_pre:      float
    n_pre:        int
    mean_post:    float
    std_post:     float
    n_post:       int
    delta:        float      # mean_post − mean_pre
    severity:     str
    analysed_at:  str

    def to_dict(self) -> dict:
        return {
            "farm":         self.farm,
            "turbine":      self.turbine,
            "event_id":     self.event_id,
            "event_start":  self.event_start,
            "event_end":    self.event_end,
            "bin":          self.bin,
            "col":          self.col,
            "mean_pre":     round(self.mean_pre,  3),
            "std_pre":      round(self.std_pre,   3),
            "n_pre":        self.n_pre,
            "mean_post":    round(self.mean_post, 3),
            "std_post":     round(self.std_post,  3),
            "n_post":       self.n_post,
            "delta":        round(self.delta,     3),
            "severity":     self.severity,
            "analysed_at":  self.analysed_at,
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyse_turbine(
    farm: str,
    turbine: str,
    db_path=DB_PATH,
) -> list[ServiceDelta]:
    """
    Run delta analysis for ALL service events of a turbine.
    Returns a flat list of ServiceDelta objects (across all events).
    """
    if not db_path.exists():
        log("WARN", "analysis_no_db", farm=farm, turbine=turbine)
        return []

    conn = sqlite3.connect(db_path)

    # Load all events so we can attach start/end metadata to each delta
    try:
        event_rows = conn.execute(
            """SELECT event_id, event_start, event_end
               FROM service_events
               WHERE farm=? AND turbine=?
               ORDER BY event_start""",
            (farm, turbine),
        ).fetchall()
    except sqlite3.OperationalError:
        conn.close()
        return []

    all_deltas: list[ServiceDelta] = []
    for (event_id, event_start, event_end) in event_rows:
        deltas = analyse_event(
            farm=farm,
            turbine=turbine,
            event_id=event_id,
            event_start=event_start,
            event_end=event_end,
            conn=conn,
        )
        all_deltas.extend(deltas)

    if all_deltas:
        _write_deltas(all_deltas, conn)

    conn.close()

    flagged = [d for d in all_deltas if d.severity not in ("NEUTRAL", "SLIGHT_IMPROVEMENT", "IMPROVED")]
    log("INFO", "analysis_turbine_done",
        farm=farm, turbine=turbine,
        events=len(event_rows),
        delta_rows=len(all_deltas),
        flagged=len(flagged))

    return all_deltas


def analyse_event(
    farm: str,
    turbine: str,
    event_id: str,
    event_start: str,
    event_end: str,
    conn: Optional[sqlite3.Connection] = None,
    db_path=DB_PATH,
) -> list[ServiceDelta]:
    """
    Run delta analysis for a single service event.

    *conn* may be passed in to reuse an existing connection; otherwise a
    new connection to *db_path* is opened and closed internally.
    """
    own_conn = conn is None
    if own_conn:
        if not db_path.exists():
            return []
        conn = sqlite3.connect(db_path)

    now_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")
    results: list[ServiceDelta] = []

    try:
        # Load all pre/post observations for this event
        rows = conn.execute(
            """SELECT phase, bin, col, value
               FROM window_observations
               WHERE farm=? AND turbine=? AND event_id=?""",
            (farm, turbine, event_id),
        ).fetchall()
    except sqlite3.OperationalError:
        if own_conn:
            conn.close()
        return []

    # Group by (phase, bin, col)
    grouped: dict[tuple[str, str, str], list[float]] = {}
    for phase, bin_key, col, value in rows:
        if col not in TEMP_COLS:
            continue
        key = (phase, bin_key, col)
        grouped.setdefault(key, []).append(value)

    # Find all (bin, col) pairs that have BOTH pre and post data
    all_bin_cols: set[tuple[str, str]] = set()
    for (phase, bin_key, col) in grouped:
        all_bin_cols.add((bin_key, col))

    for (bin_key, col) in sorted(all_bin_cols):
        pre_vals  = grouped.get(("pre",  bin_key, col), [])
        post_vals = grouped.get(("post", bin_key, col), [])

        if len(pre_vals) < MIN_OBS_PER_PHASE or len(post_vals) < MIN_OBS_PER_PHASE:
            continue

        mean_pre  = _mean(pre_vals)
        std_pre   = _std(pre_vals, mean_pre)
        mean_post = _mean(post_vals)
        std_post  = _std(post_vals, mean_post)
        delta     = mean_post - mean_pre
        severity  = _classify_severity(delta)

        results.append(ServiceDelta(
            farm=farm,
            turbine=turbine,
            event_id=event_id,
            event_start=event_start,
            event_end=event_end,
            bin=bin_key,
            col=col,
            mean_pre=mean_pre,
            std_pre=std_pre,
            n_pre=len(pre_vals),
            mean_post=mean_post,
            std_post=std_post,
            n_post=len(post_vals),
            delta=delta,
            severity=severity,
            analysed_at=now_utc,
        ))

    if own_conn:
        if results:
            _write_deltas(results, conn)
        conn.close()

    return results


def load_deltas(
    farm: str,
    turbine: Optional[str] = None,
    severity_filter: Optional[list[str]] = None,
    db_path=DB_PATH,
) -> list[dict]:
    """Load persisted service_deltas from the DB."""
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    try:
        q = "SELECT * FROM service_deltas WHERE farm=?"
        args: list = [farm]
        if turbine:
            q += " AND turbine=?"
            args.append(turbine)
        if severity_filter:
            placeholders = ",".join("?" * len(severity_filter))
            q += f" AND severity IN ({placeholders})"
            args.extend(severity_filter)
        q += " ORDER BY turbine, event_start, col, delta ASC"
        rows = conn.execute(q, args).fetchall()
        col_names = [
            "farm", "turbine", "event_id", "event_start", "event_end",
            "bin", "col", "mean_pre", "std_pre", "n_pre",
            "mean_post", "std_post", "n_post", "delta", "severity", "analysed_at",
        ]
        return [dict(zip(col_names, r)) for r in rows]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _mean(vals: list[float]) -> float:
    return sum(vals) / len(vals)


def _std(vals: list[float], mean: float) -> float:
    if len(vals) < 2:
        return 0.0
    variance = sum((v - mean) ** 2 for v in vals) / (len(vals) - 1)
    return math.sqrt(variance)


def _classify_severity(delta: float) -> str:
    """Map delta (°C) to a severity label."""
    if delta <= DELTA_IMPROVED:
        return "IMPROVED"
    if delta <= DELTA_SLIGHT_IMPROVEMENT:
        return "SLIGHT_IMPROVEMENT"
    if delta < DELTA_SLIGHT_DECLINE:
        return "NEUTRAL"
    if delta < DELTA_WORSENED:
        return "SLIGHT_DECLINE"
    return "WORSENED"


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _write_deltas(
    deltas: list[ServiceDelta],
    conn: sqlite3.Connection,
) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS service_deltas (
            farm         TEXT NOT NULL,
            turbine      TEXT NOT NULL,
            event_id     TEXT NOT NULL,
            event_start  TEXT NOT NULL,
            event_end    TEXT NOT NULL,
            bin          TEXT NOT NULL,
            col          TEXT NOT NULL,
            mean_pre     REAL,
            std_pre      REAL,
            n_pre        INTEGER,
            mean_post    REAL,
            std_post     REAL,
            n_post       INTEGER,
            delta        REAL,
            severity     TEXT,
            analysed_at  TEXT,
            PRIMARY KEY (farm, turbine, event_id, bin, col)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_deltas_turbine_sev
            ON service_deltas (farm, turbine, severity)
    """)
    conn.executemany(
        """INSERT OR REPLACE INTO service_deltas
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [
            (d.farm, d.turbine, d.event_id, d.event_start, d.event_end,
             d.bin, d.col,
             d.mean_pre, d.std_pre, d.n_pre,
             d.mean_post, d.std_post, d.n_post,
             d.delta, d.severity, d.analysed_at)
            for d in deltas
        ],
    )
    conn.commit()

