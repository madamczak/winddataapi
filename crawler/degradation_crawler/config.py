"""
config.py — Central constants for the degradation crawler.

All temperature sensor column names, conditioning variable names, binning
boundaries, and detection thresholds live here so every module stays in sync.
Edit this file to tune the detector without touching algorithm code.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Temperature signal columns — monitored for degradation
# ---------------------------------------------------------------------------
# See docs §3 "Temperature Signals Available"
TEMP_COLS: list[str] = [
    "Generator bearing front temperature (°C)",   # High priority — friction heat
    "Generator bearing rear temperature (°C)",    # High priority — axial load failures
    "Stator temperature 1 (°C)",                  # High priority — insulation aging
    "Gear oil temperature (°C)",                  # High priority — oil/gear degradation
    "Front bearing temperature (°C)",             # Medium — main shaft front
    "Rear bearing temperature (°C)",              # Medium — main shaft rear
    "Nacelle temperature (°C)",                   # Medium — cumulative; noisy
]

# ---------------------------------------------------------------------------
# Conditioning variable columns — used for normalisation, NOT monitored
# ---------------------------------------------------------------------------
COND_COLS: list[str] = [
    "Wind speed (m/s)",
    "Power (kW)",
    "Nacelle ambient temperature (°C)",
]

# Physical sanity range for temperature readings.
# Values outside this range are treated as sensor noise and skipped.
TEMP_RANGE: tuple[float, float] = (5.0, 120.0)

# ---------------------------------------------------------------------------
# Operating condition bin boundaries
# ---------------------------------------------------------------------------
# Wind speed bins (m/s) — 6 levels
WIND_BINS: list[float] = [0, 4, 6, 8, 10, 12, float("inf")]

# Power bins (kW) — 5 levels
POWER_BINS: list[float] = [0, 500, 1000, 1500, 2000, float("inf")]

# Ambient temperature bins (°C) — 5 levels
AMBIENT_BINS: list[float] = [float("-inf"), 0, 10, 20, 30, float("inf")]

# Minimum observations required in a bin before a baseline entry is stored.
MIN_BIN_OBS: int = 10

# Minimum comparable hours in an assessment window to emit a HEALTHY record.
MIN_HEALTHY_OBS: int = 30

# Minimum raw rows per API hour response (10-min intervals → 6 per hour; allow missing)
MIN_ROWS_PER_HOUR: int = 4

# ---------------------------------------------------------------------------
# Drift detection thresholds (°C)
# ---------------------------------------------------------------------------
# Rolling window length (in comparable-hour units → approx 30 calendar days)
ROLLING_WINDOW_HOURS: int = 72   # ≈ 72 comparable hours ≈ 30 calendar days

# Minimum hours in the rolling window before a drift check fires
MIN_WINDOW_FILL: int = 12

# ΔT thresholds for severity classification
WATCH_THRESHOLD:    float = 1.5   # mean ΔT °C → WATCH
WARNING_THRESHOLD:  float = 3.0   # mean ΔT °C → WARNING
CRITICAL_THRESHOLD: float = 5.0   # mean ΔT °C → CRITICAL

# Slope thresholds (°C per month, computed over 90-day window)
SLOPE_WATCH:   float = 0.2   # °C/month
SLOPE_WARNING: float = 0.4   # °C/month

# Large negative drift also flagged (possible unreported repair / sensor failure)
NEGATIVE_WATCH_THRESHOLD: float = -2.0  # °C

# ---------------------------------------------------------------------------
# Evidence scoring → severity mapping
# ---------------------------------------------------------------------------
# Each criterion adds points. Score drives the final severity label.
# See docs §15.2 "Evidence Criteria for Degradation"
SCORE_WATCH:    int = 1   # score 1–2 → WATCH
SCORE_WARNING:  int = 3   # score 3–4 → WARNING
SCORE_CRITICAL: int = 5   # score 5+  → CRITICAL

# Healthy window criteria
HEALTHY_MEAN_BOUND:  float = 1.5   # |mean ΔT| < this
HEALTHY_SLOPE_BOUND: float = 0.2   # |slope|   < this °C/month
HEALTHY_SIGMA_MULT:  float = 3.0   # σ < HEALTHY_SIGMA_MULT × baseline_bin_sigma

# ---------------------------------------------------------------------------
# Output paths (relative to the degradation_crawler package directory)
# ---------------------------------------------------------------------------
from pathlib import Path

PACKAGE_DIR  = Path(__file__).parent
RESULTS_DIR  = PACKAGE_DIR / "results"
RESIDUALS_DIR = RESULTS_DIR / "residuals"
BASELINE_DB  = PACKAGE_DIR / "baseline.db"
ALERTS_JSONL = RESULTS_DIR / "degradation_alerts.jsonl"
HEALTHY_JSONL = RESULTS_DIR / "healthy_records.jsonl"
DEGRADING_JSONL = RESULTS_DIR / "degrading_records.jsonl"

# ---------------------------------------------------------------------------
# Trend DB — cross-temporal OLS analysis (--mode trend)
# ---------------------------------------------------------------------------
TREND_DB = PACKAGE_DIR / "trend_observations.db"

# Minimum observations per (bin, col) before a trend is reported
TREND_MIN_OBS: int = 50

# Minimum time span in days between first and last observation in a bin
TREND_MIN_DAY_SPAN: int = 365

# Minimum number of distinct calendar years that must have observations in a bin
# before the trend is reported.  This prevents single-year seasonal effects from
# masquerading as multi-year degradation.
TREND_MIN_YEARS: int = 2

# OLS slope thresholds (°C / year)
TREND_WATCH_SLOPE:    float = 0.5
TREND_WARNING_SLOPE:  float = 1.5
TREND_CRITICAL_SLOPE: float = 3.0

# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
import os
API_BASE: str = os.environ.get("API_BASE", "https://winddataapi-backend.onrender.com")
