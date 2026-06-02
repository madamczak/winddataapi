"""
config.py — Central constants for the service crawler.

All column names, thresholds, window sizes, and paths live here.
"""

from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Temperature signal columns — same as degradation_crawler
# ---------------------------------------------------------------------------
TEMP_COLS: list[str] = [
    "Generator bearing front temperature (°C)",
    "Generator bearing rear temperature (°C)",
    "Stator temperature 1 (°C)",
    "Gear oil temperature (°C)",
    "Front bearing temperature (°C)",
    "Rear bearing temperature (°C)",
    "Nacelle temperature (°C)",
]

# Conditioning variables (for bin assignment — NOT directly analysed)
COND_COLS: list[str] = [
    "Wind speed (m/s)",
    "Power (kW)",
    "Nacelle ambient temperature (°C)",
]

# Physical sanity range for temperature readings
TEMP_RANGE: tuple[float, float] = (5.0, 120.0)

# ---------------------------------------------------------------------------
# Operating condition bin boundaries — identical to degradation_crawler
# ---------------------------------------------------------------------------
WIND_BINS:    list[float] = [0, 4, 6, 8, 10, 12, float("inf")]
POWER_BINS:   list[float] = [0, 500, 1000, 1500, 2000, float("inf")]
AMBIENT_BINS: list[float] = [float("-inf"), 0, 10, 20, 30, float("inf")]

# ---------------------------------------------------------------------------
# Collection constants
# ---------------------------------------------------------------------------

# How many days before service_start and after service_end to collect
WINDOW_DAYS: int = 7

# IEC category that identifies scheduled maintenance events
SCHEDULED_MAINTENANCE_CATEGORY: str = "Scheduled Maintenance"

# Minimum raw 10-min rows per API hour response (allow some gaps)
MIN_ROWS_PER_HOUR: int = 4

# Minimum observations (hourly bins) per phase (pre or post) before delta is computed
MIN_OBS_PER_PHASE: int = 10

# ---------------------------------------------------------------------------
# Delta severity thresholds (°C)
# A negative delta means the sensor is COOLER after the service — that is
# the expected outcome.  A positive delta means HOTTER — worth investigating.
# ---------------------------------------------------------------------------
DELTA_IMPROVED:           float = -3.0   # delta ≤ this  → IMPROVED
DELTA_SLIGHT_IMPROVEMENT: float = -1.0   # delta ≤ this  → SLIGHT_IMPROVEMENT
DELTA_SLIGHT_DECLINE:     float =  1.0   # delta ≥ this  → SLIGHT_DECLINE
DELTA_WORSENED:           float =  3.0   # delta ≥ this  → WORSENED

# ---------------------------------------------------------------------------
# Output paths
# ---------------------------------------------------------------------------
PACKAGE_DIR = Path(__file__).parent
DB_PATH     = PACKAGE_DIR / "service_crawler.db"
REPORT_JSONL = PACKAGE_DIR / "service_deltas.jsonl"

# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
API_BASE: str = os.environ.get("API_BASE", "https://winddataapi-backend.onrender.com")

