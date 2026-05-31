"""
run.py — Main entry point for the degradation crawler.

Two operating modes:

  --mode degradation  (default)
      Classic 5-phase pipeline per turbine:
        Phase 1 — Baseline  (skip if already built)
        Phase 2 — Scan      (ΔT residuals vs. baseline)
        Phase 3 — Service mask
        Phase 4 — Drift detection
        Phase 5 — Alert / classification output

  --mode trend
      Cross-temporal OLS analysis — no artificial baseline split:
        Phase A — Accumulate  (crawl full date range, 1 API call/day)
        Phase B — Trend fit   (OLS per bin/col → slope in °C/year)
      Produces a severity table and writes results to trend_observations.db.
      Requires at least 6 months (TREND_MIN_DAY_SPAN) and 50 observations
      (TREND_MIN_OBS) per bin/col before reporting a slope.

Usage:
    python -m degradation_crawler --farm kelmarsh
    python -m degradation_crawler --farm kelmarsh --mode trend
    python -m degradation_crawler --farm kelmarsh --turbines turbine_1,turbine_2 --mode trend
    python -m degradation_crawler --farm penmanshiel --mode trend
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date
from pathlib import Path

from .alert import write_alerts, write_assessments
from .baseline import (
    baseline_exists,
    build_baseline,
    load_baseline,
    load_baseline_std,
)
from .classify import apply_corroboration, classify_window
from .config import TEMP_COLS
from .drift_detect import detect_drift
from .machine_logger import CODE_SHA, log
from .scan import load_residuals, scan_period
from .service_mask import fetch_mask_windows


# ---------------------------------------------------------------------------
# Farm configuration — defines turbine lists and data ranges
# Extend this dict or move to farms.json as the project grows.
# ---------------------------------------------------------------------------
FARMS: dict[str, dict] = {
    "kelmarsh": {
        "turbines": [
            "turbine_1", "turbine_2", "turbine_3",
            "turbine_4", "turbine_5", "turbine_6",
        ],
        "data_start": date(2016, 6, 8),
        "data_end":   date(2020, 12, 31),
        "baseline_months": 12,   # first N months used for baseline
    },
    "penmanshiel": {
        "turbines": [f"turbine_{i}" for i in range(1, 16)],
        "data_start": date(2016, 10, 7),
        "data_end":   date(2021, 6, 30),
        "baseline_months": 12,
    },
}

# Assessment window length in comparable hours (≈ 30 calendar days)
ASSESSMENT_WINDOW_HOURS: int = 72


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Wind turbine degradation crawler.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--farm",         required=True,
                   help="Farm name: kelmarsh or penmanshiel")
    p.add_argument("--turbines",     default=None,
                   help="Comma-separated turbine IDs. Default: all in farm.")
    p.add_argument("--mode",         default="degradation",
                   choices=["degradation", "trend"],
                   help="'degradation' = classic 5-phase pipeline (default); "
                        "'trend' = full-range OLS cross-temporal analysis.")
    # degradation-mode only
    p.add_argument("--baseline-end", default=None, metavar="YYYY-MM-DD",
                   help="[degradation] Override baseline period end date.")
    p.add_argument("--scan-start",   default=None, metavar="YYYY-MM-DD",
                   help="[degradation] Override scan period start date.")
    p.add_argument("--scan-end",     default=None, metavar="YYYY-MM-DD",
                   help="[degradation] Override scan period end date.")
    p.add_argument("--skip-phase1",  action="store_true",
                   help="[degradation] Skip baseline build.")
    p.add_argument("--skip-phase4",  action="store_true",
                   help="[degradation] Skip drift detection and classification.")
    # trend-mode only
    p.add_argument("--reaccumulate", action="store_true",
                   help="[trend] Force re-accumulation even if data already exists.")
    return p.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    args = parse_args()

    farm_cfg = FARMS.get(args.farm)
    if farm_cfg is None:
        print(f"ERROR: Unknown farm '{args.farm}'. Known: {list(FARMS)}", file=sys.stderr)
        return 1

    all_turbines: list[str] = farm_cfg["turbines"]
    if args.turbines:
        requested = [t.strip() for t in args.turbines.split(",")]
        turbines = [t for t in requested if t in all_turbines]
        if not turbines:
            print(f"ERROR: None of {requested} are in farm '{args.farm}'.", file=sys.stderr)
            return 1
    else:
        turbines = all_turbines

    data_start: date = farm_cfg["data_start"]
    data_end:   date = farm_cfg["data_end"]

    t_run_start = time.time()
    log("INFO", "heartbeat_start",
        farm=args.farm,
        turbine_count=len(turbines),
        sha=CODE_SHA,
        mode=args.mode)

    # ── Trend mode ────────────────────────────────────────────────────────────
    if args.mode == "trend":
        return _run_trend_mode(args, turbines, data_start, data_end, t_run_start)

    # ── Classic degradation mode ──────────────────────────────────────────────
    from dateutil.relativedelta import relativedelta
    baseline_months: int = farm_cfg["baseline_months"]

    baseline_end = (
        date.fromisoformat(args.baseline_end)
        if args.baseline_end
        else data_start + relativedelta(months=baseline_months) - relativedelta(days=1)
    )
    scan_start = (
        date.fromisoformat(args.scan_start)
        if args.scan_start
        else baseline_end + relativedelta(days=1)
    )
    scan_end = (
        date.fromisoformat(args.scan_end)
        if args.scan_end
        else min(data_end, date.today())
    )

    log("INFO", "degradation_mode_params",
        baseline_end=str(baseline_end),
        scan_start=str(scan_start),
        scan_end=str(scan_end))

    errors = 0
    rows_total = 0

    for turbine in turbines:
        t_turbine = time.time()
        try:
            rows = _process_turbine(
                farm=args.farm,
                turbine=turbine,
                data_start=data_start,
                baseline_end=baseline_end,
                scan_start=scan_start,
                scan_end=scan_end,
                skip_phase1=args.skip_phase1,
                skip_phase4=args.skip_phase4,
            )
            rows_total += rows
            log("INFO", "turbine_done",
                farm=args.farm, turbine=turbine,
                rows=rows,
                duration_s=round(time.time() - t_turbine, 1))
        except Exception as exc:
            errors += 1
            log("ERROR", "turbine_failed",
                farm=args.farm, turbine=turbine, error=str(exc))

    log("INFO", "heartbeat_end",
        farm=args.farm,
        turbines_processed=len(turbines),
        rows_total=rows_total,
        errors=errors,
        duration_s=round(time.time() - t_run_start, 1))

    return 0 if errors == 0 else 1


def _run_trend_mode(
    args: argparse.Namespace,
    turbines: list[str],
    data_start: date,
    data_end: date,
    t_run_start: float,
) -> int:
    """
    Trend mode: accumulate full date range → fit OLS per bin/col → print summary.
    """
    from .accumulate import accumulate_turbine, observation_count, pending_day_count
    from .trend_analysis import analyse_turbine, print_trend_summary

    errors = 0
    all_results = []

    for turbine in turbines:
        t0 = time.time()
        try:
            pending = pending_day_count(args.farm, turbine, data_start, data_end)
            if pending == 0 and not args.reaccumulate:
                log("INFO", "accumulate_complete", farm=args.farm, turbine=turbine,
                    existing_obs=observation_count(args.farm, turbine),
                    note="Full date range already accumulated.")
            else:
                if pending > 0:
                    log("INFO", "accumulate_phase", farm=args.farm, turbine=turbine,
                        start=str(data_start), end=str(data_end),
                        pending_days=pending)
                accumulate_turbine(
                    farm=args.farm,
                    turbine=turbine,
                    data_start=data_start,
                    data_end=data_end,
                )

            log("INFO", "trend_analysis_phase", farm=args.farm, turbine=turbine)
            results = analyse_turbine(farm=args.farm, turbine=turbine)
            all_results.extend(results)

            flagged = [r for r in results if r.severity != "OK"]
            log("INFO", "turbine_done",
                farm=args.farm, turbine=turbine,
                trend_results=len(results),
                flagged=len(flagged),
                duration_s=round(time.time() - t0, 1))
        except Exception as exc:
            errors += 1
            log("ERROR", "turbine_failed",
                farm=args.farm, turbine=turbine, error=str(exc))

    # Print summary table to stdout
    print("\n" + "=" * 80)
    print(f"TREND ANALYSIS SUMMARY  farm={args.farm}  turbines={len(turbines)}")
    print("=" * 80)
    print_trend_summary(all_results)
    print()

    log("INFO", "heartbeat_end",
        farm=args.farm,
        mode="trend",
        turbines_processed=len(turbines),
        total_trend_results=len(all_results),
        errors=errors,
        duration_s=round(time.time() - t_run_start, 1))

    return 0 if errors == 0 else 1


# ---------------------------------------------------------------------------
# Per-turbine pipeline
# ---------------------------------------------------------------------------

def _process_turbine(
    farm: str,
    turbine: str,
    data_start: date,
    baseline_end: date,
    scan_start: date,
    scan_end: date,
    skip_phase1: bool,
    skip_phase4: bool,
) -> int:
    """
    Run all phases for one turbine.  Returns the total number of residual rows written.
    """
    # ── Phase 3: Fetch service mask (used by both Phase 1 & 2) ──────────────
    mask_windows = fetch_mask_windows(farm=farm, turbine=turbine,
                                      start_date=data_start, end_date=scan_end)

    # ── Phase 1: Build baseline (skip if already stored) ────────────────────
    if not skip_phase1 and not baseline_exists(farm=farm, turbine=turbine):
        log("INFO", "phase1_baseline", farm=farm, turbine=turbine,
            start=str(data_start), end=str(baseline_end))
        build_baseline(
            farm=farm,
            turbine=turbine,
            start_date=data_start,
            end_date=baseline_end,
            mask_windows=mask_windows,
        )

    baseline = load_baseline(farm=farm, turbine=turbine)
    if not baseline:
        log("WARN", "no_baseline_skip", farm=farm, turbine=turbine,
            note="Baseline empty — skipping scan for this turbine.")
        return 0

    baseline_std = load_baseline_std(farm=farm, turbine=turbine)

    # ── Phase 2: Scan period — compute ΔT residuals ──────────────────────────
    scan_summary = scan_period(
        farm=farm,
        turbine=turbine,
        start_date=scan_start,
        end_date=scan_end,
        baseline=baseline,
        mask_windows=mask_windows,
    )
    rows_written = scan_summary.get("residuals_written", 0)

    if skip_phase4:
        return rows_written

    # ── Phase 4: Drift detection ─────────────────────────────────────────────
    residuals = load_residuals(farm=farm, turbine=turbine)
    if not residuals:
        log("INFO", "no_residuals_skip", farm=farm, turbine=turbine)
        return rows_written

    drift_alerts = detect_drift(residuals, farm=farm, turbine=turbine)
    if drift_alerts:
        write_alerts(drift_alerts)

    # ── Phase 5: Classification (HEALTHY / DEGRADING bins) ───────────────────
    # Classify the most recent assessment window for each temperature column
    assessment_records = []
    for col in TEMP_COLS:
        col_rows = [r for r in residuals if r["col"] == col]
        if not col_rows:
            continue

        # Use last ASSESSMENT_WINDOW_HOURS comparable hours
        window = col_rows[-ASSESSMENT_WINDOW_HOURS:]

        # Get baseline std for this column (use the most common bin in the window)
        bin_std = _get_dominant_bin_std(window, baseline_std, col)
        record = classify_window(
            farm=farm,
            turbine=turbine,
            col=col,
            window_rows=window,
            baseline_bin_std=bin_std,
        )
        if record:
            assessment_records.append(record)

    # Apply multi-sensor corroboration (+2 for co-flagged subsystems)
    degrading = [r for r in assessment_records if r.bin == "DEGRADING"]
    apply_corroboration(degrading)

    healthy_n, degrading_n = write_assessments(assessment_records)
    log("INFO", "assessments_written",
        farm=farm, turbine=turbine,
        healthy=healthy_n, degrading=degrading_n)

    return rows_written


def _get_dominant_bin_std(
    window: list[dict],
    baseline_std: dict,
    col: str,
) -> float | None:
    """Return the baseline σ for the most common op_bin in the window, for *col*."""
    if not window or not baseline_std:
        return None
    from collections import Counter
    bins = [r.get("op_bin") for r in window if r.get("op_bin")]
    if not bins:
        return None
    dominant_bin = Counter(bins).most_common(1)[0][0]
    return baseline_std.get(dominant_bin, {}).get(col)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # When run directly as `python degradation_crawler/run.py` the package
    # imports won't resolve without the crawler/ parent on sys.path.
    # Add it here so both `python run.py` and `python -m degradation_crawler`
    # work correctly.
    _parent = Path(__file__).parent.parent
    if str(_parent) not in sys.path:
        sys.path.insert(0, str(_parent))
    sys.exit(main())



