#!/usr/bin/env python3
"""
collect_hourly.py — Wind Turbine Hourly Data Collector
========================================================
One-shot batch process: query → enrich with weather → summarise → save → exit.

Usage examples
--------------
# Collect one day for Kelmarsh turbine 2 (default columns, local storage)
python collect_hourly.py --farm kelmarsh --turbine turbine_2 \
    --start "2018-05-30 00:00:00" --end "2018-05-30 23:59:59"

# Use a custom column config
python collect_hourly.py --farm kelmarsh --turbine turbine_2 \
    --start "2018-05-30 00:00:00" --end "2018-05-30 23:59:59" \
    --columns configs/thermal_health.json

# Cache OWM responses to disk
python collect_hourly.py --farm kelmarsh --turbine turbine_2 \
    --start "2018-05-30 00:00:00" --end "2018-05-30 23:59:59" \
    --cache-weather

# Skip weather entirely
python collect_hourly.py --farm kelmarsh --turbine turbine_2 \
    --start "2018-05-30 00:00:00" --end "2018-05-30 23:59:59" \
    --no-weather

# All farms, all turbines, default date range
python collect_hourly.py --all

# Write to S3
python collect_hourly.py --farm kelmarsh --turbine turbine_2 \
    --start "2018-05-30 00:00:00" --end "2018-05-30 23:59:59" \
    --storage s3 --bucket my-bucket --prefix kelmarsh/2018/

# Write to Cloudflare R2
python collect_hourly.py --farm kelmarsh --turbine turbine_2 \
    --start "2018-05-30 00:00:00" --end "2018-05-30 23:59:59" \
    --storage r2 --bucket my-r2-bucket \
    --endpoint https://<account>.r2.cloudflarestorage.com
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Load .env if present (OWM_API_KEY etc.)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    def load_dotenv(*_a, **_kw):  # type: ignore[misc]
        pass  # python-dotenv not installed; env vars must be set directly

from collector import run_collection
from index_builder import build_index
from storage import build_storage
from weather import WeatherClient

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

FARMS_CONFIG = Path(__file__).parent / "farms.json"
DEFAULT_COLUMNS = Path(__file__).parent / "columns.json"

FARM_DEFAULT_RANGES = {
    "kelmarsh": ("2016-01-01 00:00:00", "2021-12-31 23:59:59"),
    "penmanshiel": ("2016-01-01 00:00:00", "2021-12-31 23:59:59"),
}


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def _setup_logging(log_file: str = "run.log") -> None:
    fmt = "%(asctime)s  %(levelname)-8s  %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Wind turbine hourly data collector — one-shot batch process.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Target selection
    target = p.add_mutually_exclusive_group()
    target.add_argument("--all", action="store_true", help="Collect all farms and turbines.")
    target.add_argument("--farm", nargs="+", metavar="FARM",
                        help="Farm name(s), e.g. kelmarsh penmanshiel")

    p.add_argument("--turbine", nargs="+", metavar="TURBINE",
                   help="Turbine name(s), e.g. turbine_1 turbine_2. Default: all turbines in farm.")

    # Date range
    p.add_argument("--start", metavar="DATETIME",
                   help='Start datetime, e.g. "2018-05-30 00:00:00"')
    p.add_argument("--end", metavar="DATETIME",
                   help='End datetime, e.g. "2018-05-30 23:59:59"')
    p.add_argument("--years", nargs="+", type=int, metavar="YEAR",
                   help="Repeat the --start/--end window for each year listed, "
                        "e.g. --years 2016 2017 2018. The year in --start/--end is replaced.")

    # Column config
    p.add_argument("--columns", metavar="PATH", default=str(DEFAULT_COLUMNS),
                   help=f"Path to columns.json config (default: {DEFAULT_COLUMNS})")

    # Storage
    p.add_argument("--storage", choices=["local", "s3", "r2"], default="local")
    p.add_argument("--output-dir", default="output",
                   help="Output directory for local storage (default: output/)")
    p.add_argument("--bucket", help="S3 / R2 bucket name")
    p.add_argument("--prefix", default="", help="S3 / R2 key prefix")
    p.add_argument("--endpoint", help="Custom endpoint URL for R2 or self-hosted S3")

    # Weather
    p.add_argument("--no-weather", action="store_true",
                   help="Skip OpenWeatherMap requests entirely.")
    p.add_argument("--cache-weather", action="store_true",
                   help="Persist weather responses to weather_cache.json between runs.")

    return p


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    args = _build_parser().parse_args()
    _setup_logging()
    log = logging.getLogger(__name__)

    t_start = time.time()

    # --- load farms config ---
    with open(FARMS_CONFIG, encoding="utf-8") as f:
        farms_cfg: dict = json.load(f)

    # --- load column config ---
    col_path = Path(args.columns)
    if col_path.exists():
        with open(col_path, encoding="utf-8") as f:
            column_cfg: dict = json.load(f)
        log.info("Column config: %s", col_path)
    else:
        log.warning("Column config not found at %s — saving ALL columns.", col_path)
        column_cfg = {}

    # --- resolve farms / turbines to process ---
    if args.all:
        farms_filter = None
        turbines_filter = None
    else:
        farms_filter = args.farm or list(farms_cfg.keys())
        turbines_filter = args.turbine or None

    # --- resolve date range(s) ---
    if args.start and args.end:
        base_start = datetime.strptime(args.start, "%Y-%m-%d %H:%M:%S")
        base_end   = datetime.strptime(args.end,   "%Y-%m-%d %H:%M:%S")
        if base_start > base_end:
            log.error("--start must be before --end")
            return 1
        if args.years:
            date_ranges = []
            for yr in sorted(args.years):
                s = base_start.replace(year=yr)
                e = base_end.replace(year=yr)
                date_ranges.append((s, e))
        else:
            date_ranges = [(base_start, base_end)]
    elif not args.start and not args.end:
        farm_name = (farms_filter or list(farms_cfg.keys()))[0]
        default_range = FARM_DEFAULT_RANGES.get(farm_name, ("2018-01-01 00:00:00", "2018-12-31 23:59:59"))
        base_start = datetime.strptime(default_range[0], "%Y-%m-%d %H:%M:%S")
        base_end   = datetime.strptime(default_range[1], "%Y-%m-%d %H:%M:%S")
        log.info("No date range supplied — using default: %s → %s", base_start, base_end)
        date_ranges = [(base_start, base_end)]
    else:
        log.error("Provide both --start and --end, or neither.")
        return 1

    # --- validate API reachability ---
    log.info("Checking API reachability at %s ...", "http://192.168.0.103:8000")
    try:
        import httpx
        httpx.get("http://192.168.0.103:8000/docs", timeout=120, verify=False).raise_for_status()
        log.info("API is reachable.")
    except Exception as exc:
        log.error("API health-check failed: %s", exc)
        return 1

    # --- build storage ---
    try:
        storage = build_storage(args)
        log.info("Storage: %s", args.storage)
    except Exception as exc:
        log.error("Failed to initialise storage: %s", exc)
        return 1

    # --- build weather client ---
    weather_client = None
    if not args.no_weather:
        api_key = os.environ.get("OWM_API_KEY", "")
        if not api_key:
            log.warning(
                "OWM_API_KEY not set. Set it in the environment or .env file. "
                "Skipping weather collection (use --no-weather to suppress this warning)."
            )
        else:
            weather_client = WeatherClient(
                api_key=api_key,
                use_disk_cache=args.cache_weather,
            )
            log.info("Weather client ready (cache-to-disk=%s).", args.cache_weather)

    # --- run ---
    log.info(
        "Starting collection | farms=%s | turbines=%s | %d date range(s)",
        farms_filter or "all",
        turbines_filter or "all",
        len(date_ranges),
    )
    for s, e in date_ranges:
        log.info("  %s  ->  %s", s.strftime("%Y-%m-%d %H:%M"), e.strftime("%Y-%m-%d %H:%M"))

    total_stats = {"hours_total": 0, "hours_ok": 0, "hours_skipped": 0,
                   "hours_missing": 0, "fetch_errors": 0, "files_written": 0}

    try:
        for start_dt, end_dt in date_ranges:
            run_stats = run_collection(
                farms_cfg=farms_cfg,
                start_dt=start_dt,
                end_dt=end_dt,
                column_cfg=column_cfg,
                storage=storage,
                weather_client=weather_client,
                farms_filter=farms_filter,
                turbines_filter=turbines_filter,
            )
            for k in total_stats:
                total_stats[k] += run_stats[k]
    except Exception as exc:
        log.exception("Fatal error during collection: %s", exc)
        return 1
    finally:
        if weather_client is not None:
            weather_client.flush_cache()

    run_stats = total_stats

    # --- rebuild wind speed index (local storage only) ---
    if args.storage == "local":
        build_index(output_dir=args.output_dir)

    # --- final summary ---
    elapsed = time.time() - t_start
    minutes, seconds = divmod(int(elapsed), 60)
    storage_desc = (
        f"local  →  {args.output_dir}/"
        if args.storage == "local"
        else f"{args.storage}  →  {args.bucket}/{args.prefix}"
    )

    print("\n" + "=" * 52)
    print("  Wind Turbine Data Collector — Run Complete")
    print("=" * 52)
    print(f"  Farm(s)       : {', '.join(farms_filter) if farms_filter else 'all'}")
    print(f"  Turbine(s)    : {', '.join(turbines_filter) if turbines_filter else 'all'}")
    period_start = date_ranges[0][0].strftime('%Y-%m-%d %H:%M')
    period_end   = date_ranges[-1][1].strftime('%Y-%m-%d %H:%M')
    print(f"  Period        : {period_start}  →  {period_end}  ({len(date_ranges)} range(s))")
    print(f"  Hours total   : {run_stats['hours_total']}")
    print(f"  Hours OK      : {run_stats['hours_ok']}")
    print(f"  Hours skipped : {run_stats['hours_skipped']}    (already existed)")
    print(f"  Hours missing : {run_stats['hours_missing']}    (data_missing=true)")
    print(f"  Fetch errors  : {run_stats['fetch_errors']}    (fetch_error=true, see run.log)")
    print(f"  Files written : {run_stats['files_written']}")
    if args.storage == "local":
        print(f"  Index         : {args.output_dir}/wind_speed_index.json")
    print(f"  Storage       : {storage_desc}")
    print(f"  Duration      : {minutes}m {seconds}s")
    print("=" * 52 + "\n")

    # Exit code: 2 if partial errors, 0 if clean
    if run_stats["fetch_errors"] > 0:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

