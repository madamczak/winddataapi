"""
patterns.py — Defines what "interesting" behaviour looks like for a turbine hour.

Each pattern is a dict with:
  description  str   — human-readable summary
  columns      list  — columns to always fetch from the API
  min_rows     int   — minimum readings required in the hour to evaluate
  criteria     list  — list of criterion dicts (ALL must pass)

Each criterion supports two forms:

  Plain column form:
    column       str           — exact column name
    agg          "mean"|"std"  — aggregation across the hour's readings
    min/max      float|None    — inclusive bounds

  Candidate column form (handles inconsistent SCADA labelling across turbines):
    column_candidates  list[str]   — try each; pick one whose values fall in
                                     physical_range (if given), else use first
    physical_range     [lo, hi]    — expected real-world range for the variable
                                     (e.g. [5, 25] for blade RPM)
    agg / min / max    same as above

NOTE: The Kelmarsh dataset has swapped column semantics across turbines:
  turbine_1  →  "Rotor speed (RPM)" ≈ generator RPM (1 000–2 000)
                "Generator RPM (RPM)" ≈ some other metric
  turbine_2  →  "Rotor speed (RPM)" ≈ blade RPM (0–15)
                "Generator RPM (RPM)" ≈ generator RPM (0–1 000)
The column_candidates mechanism picks the column whose values actually
fall in the expected physical range.
"""

PATTERNS: dict[str, dict] = {

    # ── 1. High wind, all turbines near-rated power ────────────────────────────
    #   Primary signal: Power ≥ 2 000 kW + Wind ≥ 10 m/s (robust across turbines)
    #   Secondary (optional): detect blade RPM automatically
    "high_wind_full_spin": {
        "description": (
            "All turbines running near rated power (≥ 2 000 kW) "
            "with wind ≥ 10 m/s and stable output (power std < 100 kW)."
        ),
        "columns": [
            "Date and time",
            "Power (kW)",
            "Wind speed (m/s)",
            "Rotor speed (RPM)",
            "Generator RPM (RPM)",
        ],
        "min_rows": 3,
        "criteria": [
            {"column": "Power (kW)",        "agg": "mean", "min": 2000.0, "max": None},
            {"column": "Power (kW)",        "agg": "std",  "min": None,   "max": 100.0},
            {"column": "Wind speed (m/s)",  "agg": "mean", "min": 10.0,   "max": None},
        ],
    },

    # ── 2. Blade RPM ~15, consistent across the hour ───────────────────────────
    #   Uses column_candidates to auto-detect which column holds blade RPM.
    "blade_rpm_15": {
        "description": (
            "All turbines spinning at ~15 blade RPM with std < 0.5 RPM. "
            "Auto-detects whether blade RPM is in 'Rotor speed (RPM)' or "
            "'Generator RPM (RPM)' (Kelmarsh has inconsistent labelling)."
        ),
        "columns": [
            "Date and time",
            "Rotor speed (RPM)",
            "Generator RPM (RPM)",
            "Wind speed (m/s)",
        ],
        "min_rows": 3,
        "criteria": [
            {
                "column_candidates": ["Rotor speed (RPM)", "Generator RPM (RPM)"],
                "physical_range": [5, 25],   # blade RPM is 5–25
                "agg": "mean",
                "min": 13.0,
                "max": 16.5,
            },
            {
                "column_candidates": ["Rotor speed (RPM)", "Generator RPM (RPM)"],
                "physical_range": [5, 25],
                "agg": "std",
                "min": None,
                "max": 0.5,
            },
            {"column": "Wind speed (m/s)", "agg": "mean", "min": 10.0, "max": None},
        ],
    },

    # ── 3. Farm-wide stop ─────────────────────────────────────────────────────
    "farm_stopped": {
        "description": (
            "All turbines producing < 5 kW — farm-wide stop "
            "(requested shutdown, forced outage, grid trip, etc.)."
        ),
        "columns": [
            "Date and time",
            "Power (kW)",
            "Wind speed (m/s)",
        ],
        "min_rows": 3,
        "criteria": [
            {"column": "Power (kW)", "agg": "mean", "min": None, "max": 5.0},
        ],
    },

    # ── 4. Rated power, tight tolerance ──────────────────────────────────────
    "rated_power": {
        "description": (
            "All turbines at ≥ 2 000 kW with power std < 50 kW "
            "(very stable near-rated operation)."
        ),
        "columns": [
            "Date and time",
            "Power (kW)",
            "Wind speed (m/s)",
        ],
        "min_rows": 3,
        "criteria": [
            {"column": "Power (kW)", "agg": "mean", "min": 2000.0, "max": None},
            {"column": "Power (kW)", "agg": "std",  "min": None,   "max": 50.0},
        ],
    },

    # ── 5. Partial performance: spinning but < 50 % capacity ──────────────────
    "partial_performance": {
        "description": (
            "All turbines producing 10–800 kW "
            "(curtailment, grid setpoint, wakes, sub-rated wind, etc.)."
        ),
        "columns": [
            "Date and time",
            "Power (kW)",
            "Wind speed (m/s)",
        ],
        "min_rows": 3,
        "criteria": [
            {"column": "Power (kW)", "agg": "mean", "min": 10.0,  "max": 800.0},
        ],
    },

    # ── 6. Low-wind cut-in region ─────────────────────────────────────────────
    "low_wind_cutin": {
        "description": (
            "All turbines in the cut-in wind band (4–7 m/s, producing 10–300 kW). "
            "Catches intermittent start/stop region."
        ),
        "columns": [
            "Date and time",
            "Wind speed (m/s)",
            "Power (kW)",
        ],
        "min_rows": 3,
        "criteria": [
            {"column": "Wind speed (m/s)", "agg": "mean", "min": 4.0, "max": 7.0},
            {"column": "Power (kW)",       "agg": "mean", "min": 10.0, "max": 300.0},
        ],
    },

    # ── 7. Thermal stress: high nacelle temperature ───────────────────────────
    "high_nacelle_temp": {
        "description": (
            "All turbines with nacelle temperature ≥ 35 °C "
            "while generating power (possible cooling or high-ambient event)."
        ),
        "columns": [
            "Date and time",
            "Nacelle temperature (C)",
            "Power (kW)",
        ],
        "min_rows": 3,
        "criteria": [
            {"column": "Nacelle temperature (C)", "agg": "mean", "min": 35.0, "max": None},
            {"column": "Power (kW)",               "agg": "mean", "min": 100.0, "max": None},
        ],
    },
}
