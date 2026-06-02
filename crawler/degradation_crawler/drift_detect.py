"""
drift_detect.py — Phase 4: Rolling-window drift detection.

Takes a flat list of residual records (one per turbine per hour per column)
and slides a window of ROLLING_WINDOW_HOURS comparable observations.  If the
mean ΔT within the window exceeds a threshold, a drift alert is emitted.

The window is expressed in *comparable hours* (i.e. hours where valid data
was available and a baseline bin existed), NOT calendar days.  At typical
capacity factors, 72 comparable hours ≈ 30 calendar days.

Also computes the linear slope over a separate 90-day window (resolved as
the last ~216 comparable hours) to distinguish one-off spikes from genuine
progressive drift.

Output — list of alert dicts:
{
  "farm":       "kelmarsh",
  "turbine":    "turbine_2",
  "col":        "Generator bearing front temperature (°C)",
  "severity":   "WARNING",            # or WATCH / CRITICAL
  "date":       "2020-04-10",
  "hour":       14,
  "mean_delta": 3.7,
  "window_n":   68,
  "slope_per_month": 0.41,
}
"""

from __future__ import annotations

from itertools import groupby
from typing import Optional

from .config import (
    CRITICAL_THRESHOLD,
    MIN_WINDOW_FILL,
    NEGATIVE_WATCH_THRESHOLD,
    ROLLING_WINDOW_HOURS,
    SLOPE_WARNING,
    WARNING_THRESHOLD,
    WATCH_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def detect_drift(
    residuals: list[dict],
    farm: str = "",
    turbine: str = "",
) -> list[dict]:
    """
    Slide a rolling window over *residuals* and return a list of drift alerts.

    Parameters
    ----------
    residuals : list[dict]
        Flat list from scan.load_residuals() — each entry has keys:
        date, hour, col, delta_t, op_bin.
        Must be sorted by (date, hour) ascending.
    farm, turbine : str
        Injected into each alert for provenance.

    Returns
    -------
    List of alert dicts, one per window position that triggers a threshold.
    Empty list if no thresholds are exceeded.
    """
    alerts: list[dict] = []

    # Group by column so each column has its own independent rolling window
    keyed = sorted(residuals, key=lambda r: (r["col"], r["date"], r["hour"]))

    for col, col_iter in groupby(keyed, key=lambda r: r["col"]):
        col_rows = list(col_iter)

        for i, row in enumerate(col_rows):
            # --- 30-day rolling window (last ROLLING_WINDOW_HOURS comparable obs) ---
            window_slice = col_rows[max(0, i - ROLLING_WINDOW_HOURS + 1): i + 1]
            window_deltas = [r["delta_t"] for r in window_slice]

            if len(window_deltas) < MIN_WINDOW_FILL:
                continue

            mean_delta = sum(window_deltas) / len(window_deltas)

            # --- 90-day slope window (last 216 comparable hours ≈ 90 calendar days) ---
            slope_slice = col_rows[max(0, i - 216 + 1): i + 1]
            slope = _linear_slope_per_month(slope_slice) if len(slope_slice) >= 12 else None

            severity = _classify_drift(mean_delta, slope)
            if severity is None:
                continue

            # Negative drift — possible unreported repair or sensor failure
            direction = "negative" if mean_delta < 0 else "positive"

            alerts.append({
                "farm":            farm,
                "turbine":         turbine,
                "col":             col,
                "severity":        severity,
                "direction":       direction,
                "date":            row["date"],
                "hour":            row["hour"],
                "mean_delta":      round(mean_delta, 3),
                "window_n":        len(window_deltas),
                "slope_per_month": round(slope, 4) if slope is not None else None,
            })

    return alerts


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _classify_drift(mean_delta: float, slope: Optional[float]) -> Optional[str]:
    """
    Return CRITICAL / WARNING / WATCH or None.

    Mean ΔT overrides are applied first (hard thresholds from the design doc);
    slope can escalate a WATCH to WARNING.
    """
    abs_delta = abs(mean_delta)

    # Positive drift
    if mean_delta >= CRITICAL_THRESHOLD:
        return "CRITICAL"
    if mean_delta >= WARNING_THRESHOLD:
        return "WARNING"
    if mean_delta >= WATCH_THRESHOLD:
        # Escalate to WARNING if slope also exceeds the slope-warning threshold
        if slope is not None and slope >= SLOPE_WARNING:
            return "WARNING"
        return "WATCH"

    # Negative drift (possible unreported repair / sensor issue)
    if mean_delta <= NEGATIVE_WATCH_THRESHOLD:
        return "WATCH"

    return None


def _linear_slope_per_month(rows: list[dict]) -> float:
    """
    Compute the OLS slope (°C / 30 days) of delta_t over the given window.

    Uses simple linear regression with the observation index as x.
    Converts from per-observation units to per-30-observations (≈ per month).
    """
    n = len(rows)
    if n < 2:
        return 0.0

    xs = list(range(n))
    ys = [r["delta_t"] for r in rows]

    x_mean = sum(xs) / n
    y_mean = sum(ys) / n

    numerator   = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(xs, ys))
    denominator = sum((xi - x_mean) ** 2 for xi in xs)

    if denominator == 0:
        return 0.0

    slope_per_obs = numerator / denominator
    # Scale: ROLLING_WINDOW_HOURS ≈ 30 calendar days → slope per month
    slope_per_month = slope_per_obs * ROLLING_WINDOW_HOURS
    return slope_per_month

