"""
classify.py — Evidence scoring and HEALTHY / DEGRADING classification.

Implements the two-bin output model described in docs §15:

  HEALTHY  — explicit assertion that a component was assessed and found normal.
             Only emitted when all 4 mandatory criteria are met.

  DEGRADING — WATCH / WARNING / CRITICAL sub-levels driven by a 0–7 evidence
              score computed from up to 5 real-time criteria.

The classify_window() function takes a window of residual records for one
turbine/column and returns an AssessmentRecord.

Multi-sensor corroboration (apply_corroboration()) adds +2 to each sensor's
score when ≥2 sensors in the same physical subsystem are both flagged.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from .config import (
    CRITICAL_THRESHOLD,
    HEALTHY_MEAN_BOUND,
    HEALTHY_SIGMA_MULT,
    HEALTHY_SLOPE_BOUND,
    MIN_HEALTHY_OBS,
    NEGATIVE_WATCH_THRESHOLD,
    SCORE_CRITICAL,
    SCORE_WARNING,
    SCORE_WATCH,
    SLOPE_WATCH,
    WARNING_THRESHOLD,
    WATCH_THRESHOLD,
)
from .drift_detect import _linear_slope_per_month


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class AssessmentRecord:
    """
    Output of classify_window() — one record per turbine / column / 30-day window.

    Written to healthy_records.jsonl or degrading_records.jsonl depending on bin.
    """
    farm:        str
    turbine:     str
    col:         str
    bin:         str   # "HEALTHY" or "DEGRADING"
    severity:    str   # "HEALTHY" | "WATCH" | "WARNING" | "CRITICAL"
    direction:   str   # "positive" | "negative" | "n/a"

    # Statistical evidence
    mean_delta:  float
    slope_per_month: Optional[float]
    std_delta:   Optional[float]
    n_obs:       int
    evidence_score: int

    # Assessment window
    window_start: str  # ISO date
    window_end:   str  # ISO date

    timestamp_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))

    # Criteria that fired (for explainability)
    criteria_fired: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "farm":            self.farm,
            "turbine":         self.turbine,
            "col":             self.col,
            "bin":             self.bin,
            "severity":        self.severity,
            "direction":       self.direction,
            "mean_delta":      self.mean_delta,
            "slope_per_month": self.slope_per_month,
            "std_delta":       self.std_delta,
            "n_obs":           self.n_obs,
            "evidence_score":  self.evidence_score,
            "window_start":    self.window_start,
            "window_end":      self.window_end,
            "timestamp_utc":   self.timestamp_utc,
            "criteria_fired":  self.criteria_fired,
        }


# Physical subsystems — used for multi-sensor corroboration
SUBSYSTEMS: dict[str, list[str]] = {
    "generator_bearings": [
        "Generator bearing front temperature (°C)",
        "Generator bearing rear temperature (°C)",
    ],
    "main_bearings": [
        "Front bearing temperature (°C)",
        "Rear bearing temperature (°C)",
    ],
    "stator": [
        "Stator temperature 1 (°C)",
    ],
    "gearbox": [
        "Gear oil temperature (°C)",
    ],
    "nacelle": [
        "Nacelle temperature (°C)",
    ],
}

# Reverse map: col → subsystem name
_COL_TO_SUBSYSTEM: dict[str, str] = {
    col: sub
    for sub, cols in SUBSYSTEMS.items()
    for col in cols
}


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def classify_window(
    farm: str,
    turbine: str,
    col: str,
    window_rows: list[dict],    # flat residual records for this col, sorted by date
    baseline_bin_std: Optional[float] = None,
) -> Optional[AssessmentRecord]:
    """
    Classify a sliding assessment window for one turbine / column.

    Parameters
    ----------
    window_rows : list[dict]
        Residual records (from scan.load_residuals flattened) for a single
        column; should cover the assessment window (≈ 30 comparable days).
    baseline_bin_std : float, optional
        Standard deviation of the baseline distribution for this bin.
        Needed for sigma-exceedance criterion. If None, that criterion is skipped.

    Returns
    -------
    AssessmentRecord or None (if not enough data to make any assertion).
    """
    if not window_rows:
        return None

    deltas = [r["delta_t"] for r in window_rows]
    n      = len(deltas)

    if n < 4:   # Too few rows to say anything
        return None

    mean_delta  = sum(deltas) / n
    std_delta   = statistics.pstdev(deltas) if n >= 2 else None
    slope       = _linear_slope_per_month(window_rows) if n >= 12 else None
    window_start = window_rows[0]["date"]
    window_end   = window_rows[-1]["date"]

    # --- Check HEALTHY criteria first (all 4 must pass) ---
    if n >= MIN_HEALTHY_OBS:
        healthy = _check_healthy(mean_delta, slope, std_delta, baseline_bin_std)
        if healthy:
            return AssessmentRecord(
                farm=farm, turbine=turbine, col=col,
                bin="HEALTHY", severity="HEALTHY", direction="n/a",
                mean_delta=round(mean_delta, 3),
                slope_per_month=round(slope, 4) if slope else None,
                std_delta=round(std_delta, 3) if std_delta else None,
                n_obs=n,
                evidence_score=0,
                window_start=window_start,
                window_end=window_end,
            )

    # --- Score evidence for degradation ---
    score, criteria = _score_criteria(mean_delta, slope, std_delta, baseline_bin_std)

    if score == 0 and abs(mean_delta) < WATCH_THRESHOLD:
        # Not enough data or no signal — cannot assert healthy, return None
        return None

    # Mean ΔT hard overrides
    severity = _score_to_severity(score, mean_delta)
    direction = "negative" if mean_delta <= NEGATIVE_WATCH_THRESHOLD else "positive"

    return AssessmentRecord(
        farm=farm, turbine=turbine, col=col,
        bin="DEGRADING", severity=severity, direction=direction,
        mean_delta=round(mean_delta, 3),
        slope_per_month=round(slope, 4) if slope else None,
        std_delta=round(std_delta, 3) if std_delta else None,
        n_obs=n,
        evidence_score=score,
        window_start=window_start,
        window_end=window_end,
        criteria_fired=criteria,
    )


def apply_corroboration(records: list[AssessmentRecord]) -> list[AssessmentRecord]:
    """
    Multi-sensor corroboration pass (docs §15.2, +2 per corroborated sensor).

    For each physical subsystem (e.g. generator_bearings), if ≥2 sensors in
    the subsystem both have score ≥ 1, add +2 to each of their evidence scores
    and re-derive severity.

    Parameters
    ----------
    records : list[AssessmentRecord]
        All DEGRADING records for a single (farm, turbine, window) assessment.

    Returns
    -------
    The same list, with evidence_score and severity potentially updated.
    """
    # Group records by subsystem
    subsystem_records: dict[str, list[AssessmentRecord]] = {}
    for rec in records:
        sub = _COL_TO_SUBSYSTEM.get(rec.col)
        if sub:
            subsystem_records.setdefault(sub, []).append(rec)

    for sub, sub_recs in subsystem_records.items():
        flagged = [r for r in sub_recs if r.evidence_score >= 1]
        if len(flagged) >= 2:
            for rec in flagged:
                rec.evidence_score += 2
                rec.criteria_fired.append("multi_sensor_corroboration")
                rec.severity = _score_to_severity(rec.evidence_score, rec.mean_delta)

    return records


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _check_healthy(
    mean_delta: float,
    slope: Optional[float],
    std_delta: Optional[float],
    baseline_std: Optional[float],
) -> bool:
    """Return True only if all four healthy conditions are satisfied."""
    if abs(mean_delta) >= HEALTHY_MEAN_BOUND:
        return False
    if slope is not None and abs(slope) >= HEALTHY_SLOPE_BOUND:
        return False
    if (
        std_delta is not None
        and baseline_std is not None
        and baseline_std > 0
        and std_delta > HEALTHY_SIGMA_MULT * baseline_std
    ):
        return False
    return True


def _score_criteria(
    mean_delta: float,
    slope: Optional[float],
    std_delta: Optional[float],
    baseline_std: Optional[float],
) -> tuple[int, list[str]]:
    """
    Compute the evidence score (0–5, before corroboration) and list of fired criteria.

    See docs §15.2 Evidence Criteria table.
    """
    score = 0
    fired: list[str] = []

    # Criterion 1: Mean ΔT above WATCH (+1)
    if mean_delta >= WATCH_THRESHOLD:
        score += 1
        fired.append("mean_delta_above_watch")

    # Criterion 2: Mean ΔT above WARNING (+2, replaces +1 above — net +1 more)
    if mean_delta >= WARNING_THRESHOLD:
        score += 1   # +1 extra on top of the WATCH point already added
        fired.append("mean_delta_above_warning")

    # Criterion 3: Positive slope sustained (+1)
    if slope is not None and slope >= SLOPE_WATCH:
        score += 1
        fired.append("slope_positive_sustained")

    # Criterion 4: Sigma exceedance (+1)
    if (
        std_delta is not None
        and baseline_std is not None
        and baseline_std > 0
        and mean_delta > 2 * baseline_std
    ):
        score += 1
        fired.append("sigma_exceedance")

    # Negative drift watch (+0 to score but still flagged)
    if mean_delta <= NEGATIVE_WATCH_THRESHOLD:
        fired.append("negative_drift_watch")

    return score, fired


def _score_to_severity(score: int, mean_delta: float) -> str:
    """
    Map evidence score + mean ΔT overrides to a severity label.

    Mean ΔT hard overrides always apply first.
    """
    # Hard overrides based on mean ΔT magnitude
    if mean_delta >= CRITICAL_THRESHOLD:
        return "CRITICAL"
    if mean_delta >= WARNING_THRESHOLD:
        return "WARNING"

    # Score-based classification
    if score >= SCORE_CRITICAL:
        return "CRITICAL"
    if score >= SCORE_WARNING:
        return "WARNING"
    if score >= SCORE_WATCH:
        return "WATCH"

    # Negative drift — always WATCH regardless of score
    if mean_delta <= NEGATIVE_WATCH_THRESHOLD:
        return "WATCH"

    return "WATCH"  # fallback

