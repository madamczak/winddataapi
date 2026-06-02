"""
run.py — Main entry point for the service crawler.

Crawls turbine data 1 week before and 1 week after every Scheduled
Maintenance event, then compares temperature sensor readings pre vs. post
to quantify the thermal impact of each service.

Pipeline:
  Phase A — Fetch Events
      GET /wind-farms/{farm}/{turbine}/events → filter "Scheduled Maintenance"
      → persist to service_crawler.db (service_events table)

  Phase B — Collect Window Data  (skipped if already crawled)
      For each pending event, fetch data for:
          PRE  window: [event_start − WINDOW_DAYS, event_start − 1 day]
          POST window: [event_end + 1 day,          event_end + WINDOW_DAYS]
      → persist to service_crawler.db (window_observations table)

  Phase C — Delta Analysis
      For each (event, operating-condition bin, temperature column) with
      enough pre AND post observations:
          delta = mean_post − mean_pre
      → persist to service_crawler.db (service_deltas table)

  Phase D — Report
      Print a severity-sorted table to stdout.
      Optionally export all deltas to service_deltas.jsonl.

Severity scale:
    IMPROVED          delta ≤ −3 °C   (clear thermal improvement)
    SLIGHT_IMPROVEMENT −3 < delta ≤ −1 °C
    NEUTRAL            −1 < delta < +1 °C
    SLIGHT_DECLINE     +1 ≤ delta < +3 °C
    WORSENED           delta ≥ +3 °C   (hotter after service — investigate)

Usage:
    python -m service_crawler --farm kelmarsh
    python -m service_crawler --farm kelmarsh --turbines turbine_1,turbine_3
    python -m service_crawler --farm penmanshiel --window-days 14
    python -m service_crawler --farm kelmarsh --show-neutral
    python -m service_crawler --farm kelmarsh --export-jsonl
    python -m service_crawler --farm kelmarsh --recrawl
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date
from pathlib import Path

from .analysis import analyse_turbine
from .collect import collect_event_windows
from .config import WINDOW_DAYS
from .fetch_events import fetch_and_store_events, load_all_events, load_pending_events
from .logger import CODE_SHA, log
from .report import export_jsonl, print_delta_summary, print_event_summary


# ---------------------------------------------------------------------------
# Farm configuration (mirrors degradation_crawler/run.py for consistency)
# ---------------------------------------------------------------------------
FARMS: dict[str, dict] = {
    "kelmarsh": {
        "turbines": [
            "turbine_1", "turbine_2", "turbine_3",
            "turbine_4", "turbine_5", "turbine_6",
        ],
        "data_start": date(2016, 6, 8),
        "data_end":   date(2020, 12, 31),
    },
    "penmanshiel": {
        "turbines": [f"turbine_{i}" for i in range(1, 16)],
        "data_start": date(2016, 10, 7),
        "data_end":   date(2021, 6, 30),
    },
}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Service crawler: pre/post maintenance temperature analysis.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--farm",         required=True,
                   help="Farm name: kelmarsh or penmanshiel")
    p.add_argument("--turbines",     default=None,
                   help="Comma-separated turbine IDs. Default: all in farm.")
    p.add_argument("--window-days",  type=int, default=WINDOW_DAYS,
                   help=f"Days to collect before and after each event "
                        f"(default: {WINDOW_DAYS}).")
    p.add_argument("--recrawl",      action="store_true",
                   help="Re-collect window data even for already-crawled events.")
    p.add_argument("--show-neutral", action="store_true",
                   help="Include NEUTRAL rows in the printed summary table.")
    p.add_argument("--export-jsonl", action="store_true",
                   help="Append all deltas to service_deltas.jsonl.")
    p.add_argument("--analyse-only", action="store_true",
                   help="Skip data collection, only (re-)run delta analysis "
                        "and print the report.")
    return p.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    args = parse_args()

    farm_cfg = FARMS.get(args.farm)
    if farm_cfg is None:
        print(f"ERROR: Unknown farm '{args.farm}'. Known: {list(FARMS)}",
              file=sys.stderr)
        return 1

    all_turbines: list[str] = farm_cfg["turbines"]
    if args.turbines:
        requested = [t.strip() for t in args.turbines.split(",")]
        turbines = [t for t in requested if t in all_turbines]
        if not turbines:
            print(f"ERROR: None of {requested} are in farm '{args.farm}'.",
                  file=sys.stderr)
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
        window_days=args.window_days)

    errors = 0
    all_deltas = []
    all_events_map: dict[str, list[dict]] = {}

    for turbine in turbines:
        t0 = time.time()
        try:
            deltas = _process_turbine(
                farm=args.farm,
                turbine=turbine,
                data_start=data_start,
                data_end=data_end,
                window_days=args.window_days,
                recrawl=args.recrawl,
                analyse_only=args.analyse_only,
            )
            all_deltas.extend(deltas)
            all_events_map[turbine] = load_all_events(args.farm, turbine)

            log("INFO", "turbine_done",
                farm=args.farm, turbine=turbine,
                delta_rows=len(deltas),
                duration_s=round(time.time() - t0, 1))
        except Exception as exc:
            errors += 1
            log("ERROR", "turbine_failed",
                farm=args.farm, turbine=turbine, error=str(exc))

    # ── Phase D: Report ───────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print(f"SERVICE CRAWLER SUMMARY  farm={args.farm}  "
          f"turbines={len(turbines)}  window={args.window_days} days")
    print("=" * 80)

    print_event_summary(args.farm, turbines, all_events_map)

    print("DELTA ANALYSIS  (pre-service vs. post-service temperature):")
    print()
    print_delta_summary(all_deltas, show_neutral=args.show_neutral)
    print()

    if args.export_jsonl:
        n = export_jsonl(all_deltas)
        print(f"Exported {n} delta rows to service_deltas.jsonl")

    log("INFO", "heartbeat_end",
        farm=args.farm,
        turbines_processed=len(turbines),
        total_deltas=len(all_deltas),
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
    data_end: date,
    window_days: int,
    recrawl: bool,
    analyse_only: bool,
) -> list:
    """Run all phases for one turbine.  Returns list of ServiceDelta objects."""

    if not analyse_only:
        # ── Phase A: Fetch service events ────────────────────────────────────
        log("INFO", "phase_a_fetch_events", farm=farm, turbine=turbine)
        fetch_and_store_events(
            farm=farm,
            turbine=turbine,
            data_start=data_start,
            data_end=data_end,
        )

        # ── Phase B: Collect window data ──────────────────────────────────────
        if recrawl:
            # Treat ALL events as pending when --recrawl is set
            pending = load_all_events(farm, turbine)
            # Strip the 'crawled' flag so collect_event_windows can process them
            pending = [
                {k: v for k, v in e.items() if k != "crawled"}
                for e in pending
            ]
        else:
            pending = load_pending_events(farm, turbine)

        if pending:
            log("INFO", "phase_b_collect", farm=farm, turbine=turbine,
                pending_events=len(pending))
            summary = collect_event_windows(
                farm=farm,
                turbine=turbine,
                events=pending,
                window_days=window_days,
            )
            log("INFO", "phase_b_done", farm=farm, turbine=turbine, **summary)
        else:
            log("INFO", "phase_b_skip", farm=farm, turbine=turbine,
                note="All events already crawled.")

    # ── Phase C: Delta analysis ───────────────────────────────────────────────
    log("INFO", "phase_c_analysis", farm=farm, turbine=turbine)
    deltas = analyse_turbine(farm=farm, turbine=turbine)

    return deltas


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    _parent = Path(__file__).parent.parent
    if str(_parent) not in sys.path:
        sys.path.insert(0, str(_parent))
    sys.exit(main())

